use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, RwLock};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct Extent2D {
    pub width: u32,
    pub height: u32,
}

impl Extent2D {
    pub fn new(width: u32, height: u32) -> Self {
        Self { width, height }
    }

    pub fn area(&self) -> u32 {
        self.width * self.height
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Format {
    Rgba8Unorm,
    Rgba16Float,
    Rgba32Float,
    Bgra8Unorm,
    Depth32Float,
    Depth24Stencil8,
    R8Unorm,
    Rg8Unorm,
    Rg16Float,
    Rgba8Srgb,
    Rgba16Unorm,
    Rgb10A2,
}

impl Format {
    pub fn bytes_per_pixel(&self) -> u32 {
        match self {
            Format::R8Unorm => 1,
            Format::Rg8Unorm => 2,
            Format::Rgba8Unorm | Format::Rgba8Srgb | Format::Bgra8Unorm => 4,
            Format::Rg16Float => 4,
            Format::Rgba16Float | Format::Rgba16Unorm => 8,
            Format::Rgba32Float => 16,
            Format::Depth32Float => 4,
            Format::Depth24Stencil8 => 4,
            Format::Rgb10A2 => 4,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ImageLayout {
    Undefined,
    General,
    ColorAttachmentOptimal,
    DepthAttachmentOptimal,
    TransferSrc,
    TransferDst,
    PresentSrc,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuImage {
    pub id: String,
    pub extent: Extent2D,
    pub format: Format,
    pub layout: ImageLayout,
    pub sample_count: u32,
}

impl GpuImage {
    pub fn new(id: String, extent: Extent2D, format: Format) -> Self {
        Self {
            id,
            extent,
            format,
            layout: ImageLayout::Undefined,
            sample_count: 1,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Buffer {
    pub id: String,
    pub size_bytes: u64,
    pub usage: BufferUsage,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum BufferUsage {
    Vertex,
    Index,
    Uniform,
    Storage,
    TransferSrc,
    TransferDst,
}

impl Buffer {
    pub fn new(id: String, size_bytes: u64, usage: BufferUsage) -> Self {
        Self {
            id,
            size_bytes,
            usage,
        }
    }
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct RenderResources {
    pub images: Vec<GpuImage>,
    pub buffers: Vec<Buffer>,
    pub descriptor_sets: Vec<DescriptorSet>,
    pub pipelines: Vec<ComputePipeline>,
}

impl RenderResources {
    pub fn new() -> Self {
        Self {
            images: Vec::new(),
            buffers: Vec::new(),
            descriptor_sets: Vec::new(),
            pipelines: Vec::new(),
        }
    }

    pub fn add_image(&mut self, image: GpuImage) {
        self.images.push(image);
    }

    pub fn add_buffer(&mut self, buffer: Buffer) {
        self.buffers.push(buffer);
    }

    pub fn find_image(&self, id: &str) -> Option<&GpuImage> {
        self.images.iter().find(|img| img.id == id)
    }

    pub fn find_buffer(&self, id: &str) -> Option<&Buffer> {
        self.buffers.iter().find(|buf| buf.id == id)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DescriptorSet {
    pub id: String,
    pub bindings: Vec<DescriptorBinding>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DescriptorBinding {
    pub binding: u32,
    pub descriptor_type: DescriptorType,
    pub resource_id: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum DescriptorType {
    CombinedImageSampler,
    SampledImage,
    StorageImage,
    UniformBuffer,
    StorageBuffer,
    UniformBufferDynamic,
    StorageBufferDynamic,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComputePipeline {
    pub id: String,
    pub shader_name: String,
    pub local_size_x: u32,
    pub local_size_y: u32,
    pub local_size_z: u32,
    pub push_constant_size: u32,
}

impl ComputePipeline {
    pub fn new(id: String, shader_name: String) -> Self {
        Self {
            id,
            shader_name,
            local_size_x: 8,
            local_size_y: 8,
            local_size_z: 1,
            push_constant_size: 0,
        }
    }
}

pub struct GpuResourcePool {
    image_counter: u64,
    buffer_counter: u64,
    descriptor_set_counter: u64,
    pipeline_counter: u64,
    staging_buffers: HashMap<String, Arc<RwLock<StagingBuffer>>>,
    free_staging_buffers: Vec<String>,
}

impl GpuResourcePool {
    pub fn new() -> Self {
        Self {
            image_counter: 0,
            buffer_counter: 0,
            descriptor_set_counter: 0,
            pipeline_counter: 0,
            staging_buffers: HashMap::new(),
            free_staging_buffers: Vec::new(),
        }
    }

    pub fn alloc_image_id(&mut self, extent: Extent2D, format: Format) -> String {
        self.image_counter += 1;
        format!(
            "img_{}_{}x{}",
            self.image_counter, extent.width, extent.height
        )
    }

    pub fn alloc_buffer_id(&mut self, size_bytes: u64) -> String {
        self.buffer_counter += 1;
        format!("buf_{}_{}bytes", self.buffer_counter, size_bytes)
    }

    pub fn acquire_staging_buffer(&mut self, size_bytes: u64) -> Option<String> {
        for (id, buf) in &self.staging_buffers {
            let buf = buf.read().unwrap();
            if buf.size_bytes >= size_bytes && buf.in_use == false {
                return Some(id.clone());
            }
        }
        None
    }
}

impl Default for GpuResourcePool {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug)]
pub struct StagingBuffer {
    pub id: String,
    pub size_bytes: u64,
    pub mapped: bool,
    pub in_use: bool,
}

pub struct AsyncSubmission {
    pub submission_id: String,
    pub wait_semaphores: Vec<String>,
    pub command_buffers: Vec<String>,
    pub signal_semaphores: Vec<String>,
    pub fence: Option<String>,
}

impl AsyncSubmission {
    pub fn new(submission_id: String) -> Self {
        Self {
            submission_id,
            wait_semaphores: Vec::new(),
            command_buffers: Vec::new(),
            signal_semaphores: Vec::new(),
            fence: None,
        }
    }

    pub fn add_wait(&mut self, sem: String, stage: PipelineStage) {
        self.wait_semaphores.push(format!("{}:{:?}", sem, stage));
    }

    pub fn add_command_buffer(&mut self, buf: String) {
        self.command_buffers.push(buf);
    }

    pub fn add_signal(&mut self, sem: String) {
        self.signal_semaphores.push(sem);
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PipelineStage {
    TopOfPipe,
    VertexInput,
    EarlyFragmentTests,
    LateFragmentTests,
    ColorAttachmentOutput,
    ComputeShader,
    Transfer,
    BottomOfPipe,
    Host,
}
