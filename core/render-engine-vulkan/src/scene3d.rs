use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Axis3D {
    X,
    Y,
    Z,
}

impl Default for Axis3D {
    fn default() -> Self {
        Self::Y
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Vec3 {
    pub fn zero() -> Self {
        Self {
            x: 0.0,
            y: 0.0,
            z: 0.0,
        }
    }

    pub fn one() -> Self {
        Self {
            x: 1.0,
            y: 1.0,
            z: 1.0,
        }
    }

    pub fn up() -> Self {
        Self {
            x: 0.0,
            y: 1.0,
            z: 0.0,
        }
    }

    pub fn forward() -> Self {
        Self {
            x: 0.0,
            y: 0.0,
            z: -1.0,
        }
    }

    pub fn right() -> Self {
        Self {
            x: 1.0,
            y: 0.0,
            z: 0.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Transform {
    pub position: Vec3,
    pub rotation_euler: Vec3,
    pub scale: Vec3,
}

impl Default for Transform {
    fn default() -> Self {
        Self {
            position: Vec3::zero(),
            rotation_euler: Vec3::zero(),
            scale: Vec3::one(),
        }
    }
}

impl Transform {
    pub fn translation(x: f32, y: f32, z: f32) -> Self {
        Self {
            position: Vec3 { x, y, z },
            ..Default::default()
        }
    }

    pub fn from_matrix(&self) -> [[f32; 4]; 4] {
        let cx = self.rotation_euler.x.cos();
        let sx = self.rotation_euler.x.sin();
        let cy = self.rotation_euler.y.cos();
        let sy = self.rotation_euler.y.sin();
        let cz = self.rotation_euler.z.cos();
        let sz = self.rotation_euler.z.sin();
        let sxcy = sx * cy;
        let cxcy = cx * cy;
        [
            [
                cy * cz * self.scale.x,
                cy * sz * self.scale.x,
                -sy * self.scale.x,
                0.0,
            ],
            [
                (sxcy * cz - cx * sz) * self.scale.y,
                (sxcy * sz + cx * cz) * self.scale.y,
                sx * self.scale.y,
                0.0,
            ],
            [
                (cx * cz + sx * sy * sz) * self.scale.z,
                (cx * sz - sx * sy * cz) * self.scale.z,
                cx * cy * self.scale.z,
                0.0,
            ],
            [self.position.x, self.position.y, self.position.z, 1.0],
        ]
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum SceneNodeType {
    Camera,
    Light,
    Mesh,
    Empty,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SceneNode {
    pub id: String,
    pub name: String,
    pub node_type: SceneNodeType,
    pub transform: Transform,
    pub parent_id: Option<String>,
    pub children: Vec<String>,
    pub visible: bool,
    pub lock: bool,
}

impl SceneNode {
    pub fn new(name: String, node_type: SceneNodeType) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            name,
            node_type,
            transform: Transform::default(),
            parent_id: None,
            children: Vec::new(),
            visible: true,
            lock: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Camera {
    pub node_id: String,
    pub fov: f32,
    pub near: f32,
    pub far: f32,
    pub aspect: f32,
}

impl Default for Camera {
    fn default() -> Self {
        Self {
            node_id: String::new(),
            fov: 45.0,
            near: 0.01,
            far: 1000.0,
            aspect: 16.0 / 9.0,
        }
    }
}

impl Camera {
    pub fn projection(&self) -> [[f32; 4]; 4] {
        let f = 1.0 / (self.fov / 2.0).tan();
        let nf = 1.0 / (self.near - self.far);
        [
            [f / self.aspect, 0.0, 0.0, 0.0],
            [0.0, f, 0.0, 0.0],
            [0.0, 0.0, (self.far + self.near) * nf, -1.0],
            [0.0, 0.0, 2.0 * self.far * self.near * nf, 0.0],
        ]
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Light {
    pub node_id: String,
    pub light_type: LightType,
    pub color: [f32; 3],
    pub intensity: f32,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum LightType {
    Directional,
    Point,
    Spot,
    Ambient,
    Area,
}

impl Default for Light {
    fn default() -> Self {
        Self {
            node_id: String::new(),
            light_type: LightType::Directional,
            color: [1.0, 1.0, 1.0],
            intensity: 1.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnimationClip {
    pub id: String,
    pub name: String,
    pub duration_seconds: f32,
    pub tracks: Vec<AnimationTrack>,
    pub looped: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnimationTrack {
    pub target_id: String,
    pub target_property: AnimationProperty,
    pub keyframes: Vec<AnimationKeyframe>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum AnimationProperty {
    Position,
    Rotation,
    Scale,
    Visibility,
    MaterialColor,
    Intensity,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnimationKeyframe {
    pub time_seconds: f32,
    pub value: f32,
    pub interpolation: KeyframeInterpolation,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum KeyframeInterpolation {
    Constant,
    Linear,
    Cubic,
    Bezier,
}

impl AnimationClip {
    pub fn new(name: String, duration: f32) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            name,
            duration_seconds: duration,
            tracks: Vec::new(),
            looped: false,
        }
    }

    pub fn evaluate(&self, time: f32) -> HashMap<String, f32> {
        let mut results = HashMap::new();
        let t = if self.looped {
            time % self.duration_seconds
        } else {
            time.min(self.duration_seconds)
        };
        for track in &self.tracks {
            for (i, kf) in track.keyframes.iter().enumerate() {
                if kf.time_seconds >= t {
                    let value = if i == 0 {
                        kf.value
                    } else {
                        let prev = &track.keyframes[i - 1];
                        let dt = kf.time_seconds - prev.time_seconds;
                        if dt > 0.0 {
                            let alpha = (t - prev.time_seconds) / dt;
                            prev.value + (kf.value - prev.value) * alpha
                        } else {
                            kf.value
                        }
                    };
                    results.insert(
                        format!("{}:{:?}", track.target_id, track.target_property),
                        value,
                    );
                    break;
                }
            }
        }
        results
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Scene {
    pub id: String,
    pub name: String,
    pub unit_scale: f32,
    pub up_axis: Axis3D,
    pub nodes: Vec<SceneNode>,
    pub cameras: Vec<Camera>,
    pub lights: Vec<Light>,
    pub materials: Vec<Material>,
    pub meshes: Vec<Mesh>,
    pub animations: Vec<AnimationClip>,
    pub active_camera_id: Option<String>,
    pub active_animation_id: Option<String>,
}

impl Default for Scene {
    fn default() -> Self {
        Self {
            id: String::new(),
            name: "Untitled Scene".into(),
            unit_scale: 1.0,
            up_axis: Axis3D::Y,
            nodes: Vec::new(),
            cameras: Vec::new(),
            lights: Vec::new(),
            materials: Vec::new(),
            meshes: Vec::new(),
            animations: Vec::new(),
            active_camera_id: None,
            active_animation_id: None,
        }
    }
}

impl Scene {
    pub fn new(name: String) -> Self {
        Self {
            name,
            ..Default::default()
        }
    }

    pub fn add_node(&mut self, node: SceneNode) -> String {
        let id = node.id.clone();
        self.nodes.push(node);
        id
    }

    pub fn add_material(&mut self, material: Material) -> String {
        let id = material.id.clone();
        self.materials.push(material);
        id
    }

    pub fn add_animation(&mut self, clip: AnimationClip) -> String {
        let id = clip.id.clone();
        self.animations.push(clip);
        id
    }

    pub fn find_node(&self, id: &str) -> Option<&SceneNode> {
        self.nodes.iter().find(|n| n.id == id)
    }

    pub fn find_material(&self, id: &str) -> Option<&Material> {
        self.materials.iter().find(|m| m.id == id)
    }

    pub fn find_mesh(&self, id: &str) -> Option<&Mesh> {
        self.meshes.iter().find(|m| m.id == id)
    }

    pub fn get_active_camera(&self) -> Option<&Camera> {
        self.active_camera_id
            .as_ref()
            .and_then(|id| self.cameras.iter().find(|c| c.node_id == *id))
    }

    pub fn get_lights_of_type(&self, light_type: LightType) -> Vec<&Light> {
        self.lights
            .iter()
            .filter(|l| l.light_type == light_type)
            .collect()
    }
}

impl Light {
    pub fn point(node_id: String, color: [f32; 3], intensity: f32) -> Self {
        Self {
            node_id,
            light_type: LightType::Point,
            color,
            intensity,
            ..Default::default()
        }
    }

    pub fn spot(
        node_id: String,
        color: [f32; 3],
        intensity: f32,
        angle: f32,
        penumbra: f32,
    ) -> Self {
        Self {
            node_id,
            light_type: LightType::Spot,
            color,
            intensity,
            ..Default::default()
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Material {
    pub id: String,
    pub name: String,
    pub material_type: MaterialType,
    pub base_color: [f32; 4],
    pub metallic: f32,
    pub roughness: f32,
    pub normal_strength: f32,
    pub emission: [f32; 3],
    pub emission_strength: f32,
    pub alpha_mode: AlphaMode,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum MaterialType {
    Pbr,
    Unlit,
    Subsurface,
    Cloth,
    Hair,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum AlphaMode {
    Opaque,
    Mask,
    Blend,
}

impl Default for Material {
    fn default() -> Self {
        Self {
            id: String::new(),
            name: "Default Material".into(),
            material_type: MaterialType::Pbr,
            base_color: [0.8, 0.8, 0.8, 1.0],
            metallic: 0.0,
            roughness: 0.5,
            normal_strength: 1.0,
            emission: [0.0, 0.0, 0.0],
            emission_strength: 0.0,
            alpha_mode: AlphaMode::Opaque,
        }
    }
}

impl Material {
    pub fn new(name: String) -> Self {
        Self {
            name,
            ..Default::default()
        }
    }

    pub fn metallic(&mut self, metallic: f32) -> &mut Self {
        self.metallic = metallic;
        self
    }

    pub fn roughness(&mut self, roughness: f32) -> &mut Self {
        self.roughness = roughness;
        self
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mesh {
    pub id: String,
    pub name: String,
    pub vertex_count: u32,
    pub index_count: u32,
    pub bounding_box: BoundingBox,
    pub material_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BoundingBox {
    pub min: Vec3,
    pub max: Vec3,
}

impl BoundingBox {
    pub fn new(min: Vec3, max: Vec3) -> Self {
        Self { min, max }
    }

    pub fn center(&self) -> Vec3 {
        Vec3 {
            x: (self.min.x + self.max.x) * 0.5,
            y: (self.min.y + self.max.y) * 0.5,
            z: (self.min.z + self.max.z) * 0.5,
        }
    }

    pub fn size(&self) -> Vec3 {
        Vec3 {
            x: self.max.x - self.min.x,
            y: self.max.y - self.min.y,
            z: self.max.z - self.min.z,
        }
    }

    pub fn includes(&self, point: &Vec3) -> bool {
        point.x >= self.min.x
            && point.x <= self.max.x
            && point.y >= self.min.y
            && point.y <= self.max.y
            && point.z >= self.min.z
            && point.z <= self.max.z
    }
}

impl Default for BoundingBox {
    fn default() -> Self {
        Self {
            min: Vec3::zero(),
            max: Vec3::one(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Skeleton {
    pub id: String,
    pub bones: Vec<Bone>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bone {
    pub id: String,
    pub name: String,
    pub parent_id: Option<String>,
    pub local_position: Vec3,
    pub local_rotation: Vec3,
    pub local_scale: Vec3,
    pub bind_matrix: [[f32; 4]; 4],
}

impl Skeleton {
    pub fn new(name: String) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            bones: Vec::new(),
        }
    }

    pub fn add_bone(&mut self, bone: Bone) -> String {
        let id = bone.id.clone();
        self.bones.push(bone);
        id
    }
}

impl Default for Mesh {
    fn default() -> Self {
        Self {
            id: String::new(),
            name: "Untitled Mesh".into(),
            vertex_count: 0,
            index_count: 0,
            bounding_box: BoundingBox::default(),
            material_id: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vec3_creation() {
        let v = Vec3::up();
        assert_eq!(v.y, 1.0);
    }

    #[test]
    fn transform_identity() {
        let t = Transform::default();
        let m = t.from_matrix();
        assert_eq!(m[3][3], 1.0);
    }
}
