use serde::{Deserialize, Serialize};

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
        Self { x: 0.0, y: 0.0, z: 0.0 }
    }

    pub fn one() -> Self {
        Self { x: 1.0, y: 1.0, z: 1.0 }
    }

    pub fn up() -> Self {
        Self { x: 0.0, y: 1.0, z: 0.0 }
    }

    pub fn forward() -> Self {
        Self { x: 0.0, y: 0.0, z: -1.0 }
    }

    pub fn right() -> Self {
        Self { x: 1.0, y: 0.0, z: 0.0 }
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
            [
                self.position.x,
                self.position.y,
                self.position.z,
                1.0,
            ],
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
pub struct Scene {
    pub id: String,
    pub name: String,
    pub unit_scale: f32,
    pub up_axis: Axis3D,
    pub nodes: Vec<SceneNode>,
    pub cameras: Vec<Camera>,
    pub lights: Vec<Light>,
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

    pub fn find_node(&self, id: &str) -> Option<&SceneNode> {
        self.nodes.iter().find(|n| n.id == id)
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