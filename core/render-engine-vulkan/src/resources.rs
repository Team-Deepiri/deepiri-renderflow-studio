use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct Extent2D {
    pub width: u32,
    pub height: u32,
}

impl Extent2D {
    pub fn new(width: u32, height: u32) -> Self {
        Self { width, height }
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
}

impl RenderResources {
    pub fn new() -> Self {
        Self {
            images: Vec::new(),
            buffers: Vec::new(),
        }
    }

    pub fn add_image(&mut self, image: GpuImage) {
        self.images.push(image);
    }

    pub fn add_buffer(&mut self, buffer: Buffer) {
        self.buffers.push(buffer);
    }
}