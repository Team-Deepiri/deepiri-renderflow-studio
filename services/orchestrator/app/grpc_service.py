from __future__ import annotations

import logging
import sys
from concurrent import futures
from pathlib import Path
from uuid import UUID

import grpc

logger = logging.getLogger(__name__)

_GEN = Path(__file__).resolve().parent / "gen"
if str(_GEN) not in sys.path:
    sys.path.insert(0, str(_GEN))

import renderflow_pb2  # noqa: E402
import renderflow_pb2_grpc  # noqa: E402

from app import memory_store  # noqa: E402
from app.api.schemas.studio import AssetCreate  # noqa: E402
from app.job_store import store  # noqa: E402
from app.runtime_state import get_settings  # noqa: E402
from app.services import studio  # noqa: E402
from app.worker_loop import enqueue_job  # noqa: E402


class AiSessionServicer(renderflow_pb2_grpc.AiSessionServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def SubmitAiJob(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid project_id")
            return renderflow_pb2.SubmitAiJobResponse()
        job = store.create(pid, request.mode or "scene", request.prompt or "")
        enqueue_job(str(job.id), get_settings())
        return renderflow_pb2.SubmitAiJobResponse(job_id=str(job.id), status=job.status.value)

    def GetJobStatus(self, request, context):  # type: ignore[no-untyped-def]
        try:
            jid = UUID(request.job_id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid job_id")
            return renderflow_pb2.JobStatusResponse()
        rec = store.get(jid)
        if not rec:
            context.abort(grpc.StatusCode.NOT_FOUND, "job not found")
            return renderflow_pb2.JobStatusResponse()
        return renderflow_pb2.JobStatusResponse(
            job_id=str(rec.id),
            status=rec.status.value,
            stages=list(rec.stages),
        )

    def CancelJob(self, request, context):  # type: ignore[no-untyped-def]
        try:
            jid = UUID(request.job_id)
        except ValueError:
            return renderflow_pb2.CancelJobResponse(success=False)
        rec = store.get(jid)
        if not rec:
            return renderflow_pb2.CancelJobResponse(success=False)
        store.update_status(jid, "cancelled")
        return renderflow_pb2.CancelJobResponse(success=True)

    def CommitArtifact(self, request, context):  # type: ignore[no-untyped-def]
        try:
            jid = UUID(request.job_id)
            aid = UUID(request.artifact_id)
        except ValueError:
            return renderflow_pb2.CommitArtifactResponse(success=False, asset_id="")
        store.mark_artifact_committed(jid, aid)
        return renderflow_pb2.CommitArtifactResponse(success=True, asset_id=str(aid))


def _proj_msg(row: dict) -> renderflow_pb2.Project:
    return renderflow_pb2.Project(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]),
        name=str(row["name"]),
        fps_num=int(row.get("fps_num", 24)),
        fps_den=int(row.get("fps_den", 1)),
        sample_rate=int(row.get("sample_rate", 48_000)),
    )


class ProjectServicer(renderflow_pb2_grpc.ProjectServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def CreateProject(self, request, context):  # type: ignore[no-untyped-def]
        studio.bootstrap()
        oid = UUID(request.owner_id) if request.owner_id else memory_store.DEMO_OWNER
        row = studio.create_project(
            oid,
            request.name or "Untitled",
            request.fps_num or 24,
            request.fps_den or 1,
            request.sample_rate or 48_000,
        )
        return _proj_msg(row)

    def GetProject(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid project_id")
            return renderflow_pb2.Project()
        row = studio.get_project(pid)
        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, "project not found")
            return renderflow_pb2.Project()
        return _proj_msg(row)

    def ListProjects(self, request, context):  # type: ignore[no-untyped-def]
        studio.bootstrap()
        oid = UUID(request.owner_id) if request.owner_id else None
        rows = studio.list_projects(oid)
        return renderflow_pb2.ListProjectsResponse(projects=[_proj_msg(r) for r in rows])

    def UpdateProject(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            return renderflow_pb2.Project()
        row = studio.update_project(pid, request.name, request.fps_num, request.fps_den)
        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, "project not found")
        return _proj_msg(row)

    def DeleteProject(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            return renderflow_pb2.DeleteProjectResponse(success=False)
        studio.delete_project(pid)
        return renderflow_pb2.DeleteProjectResponse(success=True)


class AssetServicer(renderflow_pb2_grpc.AssetServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def CreateAsset(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            return renderflow_pb2.Asset()
        row = studio.create_asset(
            pid,
            request.kind or "video",
            request.uri,
            request.sha256 or "",
            request.duration_ms or 0,
        )
        return renderflow_pb2.Asset(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            kind=str(row["kind"]),
            uri=str(row["uri"]),
            sha256=str(row.get("sha256", "")),
            duration_ms=int(row.get("duration_ms", 0)),
        )

    def GetAsset(self, request, context):  # type: ignore[no-untyped-def]
        try:
            aid = UUID(request.asset_id)
        except ValueError:
            return renderflow_pb2.Asset()
        row = studio.get_asset(aid)
        if not row:
            return renderflow_pb2.Asset()
        return renderflow_pb2.Asset(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            kind=str(row["kind"]),
            uri=str(row["uri"]),
        )

    def ListAssets(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            return renderflow_pb2.ListAssetsResponse(assets=[])
        rows = studio.list_assets(pid)
        assets = [
            renderflow_pb2.Asset(
                id=str(r["id"]),
                project_id=str(r["project_id"]),
                kind=str(r["kind"]),
                uri=str(r["uri"]),
            )
            for r in rows
        ]
        return renderflow_pb2.ListAssetsResponse(assets=assets)

    def GetAssetUri(self, request, context):  # type: ignore[no-untyped-def]
        try:
            aid = UUID(request.asset_id)
        except ValueError:
            return renderflow_pb2.GetAssetUriResponse(uri="")
        row = studio.get_asset(aid)
        if not row:
            return renderflow_pb2.GetAssetUriResponse(uri="")
        return renderflow_pb2.GetAssetUriResponse(uri=str(row["uri"]))


class SequenceServicer(renderflow_pb2_grpc.SequenceServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def CreateSequence(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            return renderflow_pb2.Sequence()
        row = studio.create_sequence(
            pid,
            request.name or "Untitled Sequence",
            request.resolution_w or 1920,
            request.resolution_h or 1080,
        )
        return renderflow_pb2.Sequence(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            name=str(row["name"]),
            resolution_w=int(row.get("resolution_w", 1920)),
            resolution_h=int(row.get("resolution_h", 1080)),
        )

    def GetSequence(self, request, context):  # type: ignore[no-untyped-def]
        try:
            sid = UUID(request.sequence_id)
        except ValueError:
            return renderflow_pb2.Sequence()
        row = studio.get_sequence(sid)
        if not row:
            return renderflow_pb2.Sequence()
        return renderflow_pb2.Sequence(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            name=str(row["name"]),
            resolution_w=int(row.get("resolution_w", 1920)),
            resolution_h=int(row.get("resolution_h", 1080)),
        )

    def ListSequences(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            return renderflow_pb2.ListSequencesResponse(sequences=[])
        rows = studio.list_sequences(pid)
        seqs = [
            renderflow_pb2.Sequence(
                id=str(r["id"]),
                project_id=str(r["project_id"]),
                name=str(r["name"]),
            )
            for r in rows
        ]
        return renderflow_pb2.ListSequencesResponse(sequences=seqs)


class TimelineServicer(renderflow_pb2_grpc.TimelineServiceServicer):
    def ResolveActiveClips(self, request, context):  # type: ignore[no-untyped-def]
        try:
            sid = UUID(request.sequence_id)
        except ValueError:
            return renderflow_pb2.ResolveActiveClipsResponse(clips=[], tracks=[])
        playhead = request.playhead_tick
        clips_data = studio.get_active_clips(sid, playhead)
        tracks_data = studio.get_tracks(sid)
        clips = [
            renderflow_pb2.Clip(
                id=str(c["id"]),
                track_id=str(c["track_id"]),
                asset_id=str(c["asset_id"]),
                in_tick=c["in_tick"],
                out_tick=c["out_tick"],
                src_in_tick=c["src_in_tick"],
            )
            for c in clips_data
        ]
        tracks = [
            renderflow_pb2.Track(
                id=str(t["id"]),
                sequence_id=str(t["sequence_id"]),
                track_type=str(t["track_type"]),
                lane_index=t["lane_index"],
                name=t["name"],
            )
            for t in tracks_data
        ]
        return renderflow_pb2.ResolveActiveClipsResponse(clips=clips, tracks=tracks)

    def GetClipFrame(self, request, context):  # type: ignore[no-untyped-def]
        try:
            aid = UUID(request.asset_id)
        except ValueError:
            return renderflow_pb2.GetClipFrameResponse(texture_id="")
        texture_id = f"frame_{aid}_{request.frame_index}"
        return renderflow_pb2.GetClipFrameResponse(texture_id=texture_id)


class RenderServicer(renderflow_pb2_grpc.RenderServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def SubmitRenderJob(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
            sid = UUID(request.sequence_id) if request.sequence_id else None
        except ValueError:
            return renderflow_pb2.RenderJob()
        job = studio.create_render_job(pid, sid, request.preset, request.output_uri)
        return renderflow_pb2.RenderJob(
            id=str(job["id"]),
            project_id=str(job["project_id"]),
            sequence_id=str(job.get("sequence_id", "")),
            preset=str(job.get("preset", "h264_1080p")),
            status=str(job.get("status", "queued")),
        )

    def GetRenderJob(self, request, context):  # type: ignore[no-untyped-def]
        try:
            jid = UUID(request.job_id)
        except ValueError:
            return renderflow_pb2.RenderJob()
        job = studio.get_render_job(jid)
        if not job:
            return renderflow_pb2.RenderJob()
        return renderflow_pb2.RenderJob(
            id=str(job["id"]),
            project_id=str(job["project_id"]),
            status=str(job.get("status", "unknown")),
        )

    def ListRenderJobs(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            return renderflow_pb2.ListRenderJobsResponse(jobs=[])
        jobs = studio.list_render_jobs(pid)
        return renderflow_pb2.ListRenderJobsResponse(
            jobs=[
                renderflow_pb2.RenderJob(
                    id=str(j["id"]),
                    project_id=str(j["project_id"]),
                    status=str(j.get("status", "unknown")),
                )
                for j in jobs
            ]
        )


class AudioServicer(renderflow_pb2_grpc.AudioServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def CheckMicrophone(self, request, context):  # type: ignore[no-untyped-def]
        from app.media import audio_recording
        result = audio_recording.check_microphone()
        return renderflow_pb2.AudioCheckResponse(
            available=result.get("available", False),
            status=result.get("ok", False),
        )

    def StartRecording(self, request, context):  # type: ignore[no-untyped-def]
        from app.media import audio_recording
        recorder = audio_recording.get_recorder()
        result = recorder.start_recording(request.output_path)
        return renderflow_pb2.AudioRecordResponse(
            success=result.get("ok", False),
            error=result.get("error", ""),
        )

    def StopRecording(self, request, context):  # type: ignore[no-untyped-def]
        from app.media import audio_recording
        recorder = audio_recording.get_recorder()
        result = recorder.stop_recording()
        return renderflow_pb2.AudioRecordResponse(
            success=result.get("ok", False),
            output_path=result.get("output", ""),
        )

    def GenerateTTS(self, request, context):  # type: ignore[no-untyped-def]
        from app.media import tts_service
        result = tts_service.generate_speech(
            request.text,
            request.output_path,
            request.engine,
            request.voice,
        )
        return renderflow_pb2.TTSResponse(
            success=result.get("ok", False),
            output_path=result.get("output", ""),
            engine=result.get("engine", ""),
        )

    def ListVoices(self, request, context):  # type: ignore[no-untyped-def]
        from app.media import tts_service
        voices = tts_service.list_voices()
        return renderflow_pb2.VoiceListResponse(
            voices=voices.get("voices", {}),
        )


class AnimationServicer(renderflow_pb2_grpc.AnimationServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def GenerateVoiceAnimation(self, request, context):  # type: ignore[no-untyped-def]
        from app.media.voice_animation_pipeline import pipeline
        result = asyncio.run(
            pipeline.run(
                request.audio_path,
                request.prompt,
            )
        )
        return renderflow_pb2.AnimationResponse(
            success=result.get("ok", False),
            transcript=result.get("transcript", ""),
            emotion=result.get("emotion", ""),
            gesture_count=result.get("gesture_count", 0),
        )


def start_grpc_server() -> grpc.Server:
    settings = get_settings()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    renderflow_pb2_grpc.add_AiSessionServiceServicer_to_server(AiSessionServicer(), server)
    renderflow_pb2_grpc.add_ProjectServiceServicer_to_server(ProjectServicer(), server)
    renderflow_pb2_grpc.add_AssetServiceServicer_to_server(AssetServicer(), server)
    renderflow_pb2_grpc.add_SequenceServiceServicer_to_server(SequenceServicer(), server)
    renderflow_pb2_grpc.add_TimelineServiceServicer_to_server(TimelineServicer(), server)
    renderflow_pb2_grpc.add_RenderServiceServicer_to_server(RenderServicer(), server)
    renderflow_pb2_grpc.add_AudioServiceServicer_to_server(AudioServicer(), server)
    renderflow_pb2_grpc.add_AnimationServiceServicer_to_server(AnimationServicer(), server)
    addr = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(addr)
    server.start()
    logger.info("gRPC services listening on %s", addr)
    return server
