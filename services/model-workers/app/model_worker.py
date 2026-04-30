"""PyTorch model workers with GPU detection and inference."""
from __future__ import annotations
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from uuid import UUID
logger = logging.getLogger(__name__)

class DeviceType(str, Enum):
    CUDA = "cuda"
    MPS = "mps"
    CPU = "cpu"

@dataclass
class GPUInfo:
    id: int
    name: str
    memory_total: int
    memory_free: int
    compute_capability: tuple[int, int]

@dataclass
class ModelConfig:
    model_id: str
    model_path: str | None = None
    model_url: str | None = None
    device: DeviceType = DeviceType.CPU
    batch_size: int = 1
    dtype: str = "float16"
    max_tokens: int = 512

@dataclass
class InferenceRequest:
    request_id: str
    model_id: str
    input_text: str
    mode: str = "generate"
    max_length: int = 200
    temperature: float = 0.7
    top_p: float = 0.9
    callback: Callable | None = None

@dataclass
class InferenceResult:
    request_id: str
    output_text: str
    finish_reason: str
    tokens_generated: int
    inference_ms: float
    device_used: DeviceType

def get_gpu_info() -> list[GPUInfo]:
    gpus = []
    try:
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                mem_total = int(props.total_memory)
                mem_free = mem_total - int(torch.cuda.memory_allocated(i))
                compute = (props.major, props.minor)
                gpus.append(
                    GPUInfo(
                        id=i,
                        name=props.name.decode().rstrip("\x00"),
                        memory_total=mem_total,
                        memory_free=mem_free,
                        compute_capability=compute,
                    )
                )
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            gpus.append(
                GPUInfo(
                    id=0,
                    name="Apple MPS",
                    memory_total=0,
                    memory_free=0,
                    compute_capability=(0, 0),
                )
            )
    except ImportError:
        logger.warning("torch not available")
    return gpus

def get_best_device() -> DeviceType:
    gpus = get_gpu_info()
    if not gpus:
        return DeviceType.CPU
    if any(gpu.name.startswith("NVIDIA") for gpu in gpus):
        return DeviceType.CUDA
    if any(gpu.name == "Apple MPS" for gpu in gpus):
        return DeviceType.MPS
    return DeviceType.CPU

def check_torch() -> dict[str, Any]:
    try:
        import torch
        torch_version = torch.__version__
        cuda = torch.cuda.is_available()
        mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        gpu_count = torch.cuda.device_count() if cuda else 0
        gpus = [{"id": g.id, "name": g.name, "mem": g.memory_total} for g in get_gpu_info()]
        return {
            "ok": True,
            "torch_version": torch_version,
            "cuda": cuda,
            "mps": mps,
            "gpu_count": gpu_count,
            "gpus": gpus,
            "device": get_best_device().value,
        }
    except ImportError:
        return {"ok": False, "error": "torch not installed"}

class ModelWorker:
    def __init__(
        self,
        config: ModelConfig,
        on_result: Callable[[InferenceResult], None] | None = None,
    ) -> None:
        self.config = config
        self.on_result = on_result
        self._model = None
        self._device = config.device
        self._lock = threading.Lock()
        self._loaded = False

    def load(self) -> dict[str, Any]:
        with self._lock:
            if self._loaded:
                return {"ok": True, "loaded": True}
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
                model_path = self.config.model_path or self.config.model_id
                dtype = getattr(torch, self.config.dtype, torch.float16)
                self._model = AutoModelForCausalLM.from_pretrained(
                    model_path,
                    torch_dtype=dtype,
                    low_cpu_mem_usage=True,
                )
                device = self._device.value
                self._model = self._model.to(device)
                self._tokenizer = AutoTokenizer.from_pretrained(model_path)
                self._loaded = True
                return {"ok": True, "loaded": True, "device": device}
            except Exception as e:
                logger.warning("load model: %s", e)
                return {"ok": False, "error": str(e)}

    def unload(self) -> dict[str, Any]:
        with self._lock:
            self._model = None
            self._tokenizer = None
            self._loaded = False
            import gc; gc.collect()
            try: import torch; torch.cuda.empty_cache()
            except: pass
        return {"ok": True}

    def is_loaded(self) -> bool:
        return self._loaded

    def infer(self, request: InferenceRequest) -> InferenceResult:
        import time
        start = time.time()
        if not self._loaded:
            self.load()
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
            if self._model is None:
                model_path = self.config.model_path or self.config.model_id
                self._model = AutoModelForCausalLM.from_pretrained(
                    model_path,
                    torch_dtype=getattr(torch, self.config.dtype, torch.float16),
                )
                self._tokenizer = AutoTokenizer.from_pretrained(model_path)
                device = self._device.value
                self._model = self._model.to(device)
                self._loaded = True
            inputs = self._tokenizer(request.input_text, return_tensors="pt")
            inputs = {k: v.to(self._device.value) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_length=request.max_length,
                    temperature=request.temperature,
                    top_p=request.top_p,
                )
            output = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
            tokens = len(outputs[0]) - len(inputs["input_ids"][0])
            ms = (time.time() - start) * 1000
            result = InferenceResult(
                request_id=request.request_id,
                output_text=output,
                finish_reason="stop",
                tokens_generated=tokens,
                inference_ms=ms,
                device_used=self._device,
            )
            if self.on_result:
                self.on_result(result)
            return result
        except Exception as e:
            logger.warning("infer: %s", e)
            ms = (time.time() - start) * 1000
            return InferenceResult(
                request_id=request.request_id,
                output_text="",
                finish_reason="error",
                tokens_generated=0,
                inference_ms=ms,
                device_used=self._device,
            )

class ModelWorkerPool:
    def __init__(self) -> None:
        self._workers: dict[str, ModelWorker] = {}
        self._config: dict[str, ModelConfig] = {}
        self._lock = threading.Lock()
        self._inference_thread: threading.Thread | None = None
        self._running = False
        self._queue: list[InferenceRequest] = []

    def register_model(self, model_id: str, config: ModelConfig) -> None:
        with self._lock:
            self._config[model_id] = config

    def get_worker(self, model_id: str) -> ModelWorker | None:
        with self._lock:
            if model_id not in self._workers:
                if model_id in self._config:
                    self._workers[model_id] = ModelWorker(self._config[model_id])
            return self._workers.get(model_id)

    def enqueue(self, request: InferenceRequest) -> str:
        with self._lock:
            self._queue.append(request)
        if self._inference_thread is None or not self._inference_thread.is_alive():
            self._inference_thread = threading.Thread(target=self._process_queue, daemon=True)
            self._inference_thread.start()
        return request.request_id

    def _process_queue(self) -> None:
        self._running = True
        while self._running and self._queue:
            request = None
            with self._lock:
                if self._queue:
                    request = self._queue.pop(0)
            if request:
                worker = self.get_worker(request.model_id)
                if worker:
                    worker.infer(request)
        self._running = False

    def stop(self) -> None:
        self._running = False
        with self._lock:
            for w in self._workers.values():
                w.unload()
            self._workers.clear()

pool = ModelWorkerPool()