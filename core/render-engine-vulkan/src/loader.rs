//! Vulkan loader: instance creation + physical device discovery (requires ICD at runtime).

use ash::vk;
use serde::Serialize;
use std::ffi::{CStr, CString};

#[derive(Debug, Clone, Serialize)]
pub struct DeviceInfo {
    pub name: String,
    pub device_id: u32,
    pub device_type: String,
    pub driver_version: u32,
    pub api_version: (u32, u32, u32),
}

#[derive(Debug, Clone, Serialize)]
pub struct VulkanDiscovery {
    pub loader_api_version: (u32, u32, u32),
    pub devices: Vec<DeviceInfo>,
}

pub fn enumerate_api_version() -> Result<u32, String> {
    unsafe {
        let entry = ash::Entry::load().map_err(|e| e.to_string())?;
        let v = entry
            .try_enumerate_instance_version()
            .map_err(|e| e.to_string())?
            .unwrap_or(vk::API_VERSION_1_0);
        Ok(v)
    }
}

pub fn version_major_minor_patch(v: u32) -> (u32, u32, u32) {
    (
        vk::api_version_major(v),
        vk::api_version_minor(v),
        vk::api_version_patch(v),
    )
}

/// Create a headless instance, list physical devices, then tear down. Used for capability checks and studio UI.
pub fn discover() -> Result<VulkanDiscovery, String> {
    unsafe {
        let entry = ash::Entry::load().map_err(|e| e.to_string())?;
        let loader_ver = entry
            .try_enumerate_instance_version()
            .map_err(|e| e.to_string())?
            .unwrap_or(vk::API_VERSION_1_0);

        let app_name = CString::new("DeepiriRenderflow").map_err(|e| e.to_string())?;
        let engine_name = CString::new("Renderflow").map_err(|e| e.to_string())?;
        let app_info = vk::ApplicationInfo::default()
            .application_name(app_name.as_c_str())
            .application_version(vk::make_api_version(0, 1, 0, 0))
            .engine_name(engine_name.as_c_str())
            .engine_version(vk::make_api_version(0, 1, 0, 0))
            .api_version(vk::API_VERSION_1_2);

        let create_info = vk::InstanceCreateInfo::default().application_info(&app_info);
        let instance: ash::Instance = entry
            .create_instance(&create_info, None)
            .map_err(|e| format!("create_instance: {e}"))?;

        let phys = instance
            .enumerate_physical_devices()
            .map_err(|e| format!("enumerate_physical_devices: {e}"))?;

        let mut devices = Vec::with_capacity(phys.len());
        for d in phys {
            let p = instance.get_physical_device_properties(d);
            let name = CStr::from_ptr(p.device_name.as_ptr())
                .to_string_lossy()
                .into_owned();
            let api = p.api_version;
            devices.push(DeviceInfo {
                name,
                device_id: p.device_id,
                device_type: format!("{:?}", p.device_type),
                driver_version: p.driver_version,
                api_version: version_major_minor_patch(api),
            });
        }

        instance.destroy_instance(None);

        Ok(VulkanDiscovery {
            loader_api_version: version_major_minor_patch(loader_ver),
            devices,
        })
    }
}
