"""Nominal sensor values, output noise, units and dashboard warning thresholds."""


def metric(key, label, nominal, unit, noise=0, digits=2, **limits):
    return dict(key=key, label=label, nominal=nominal, unit=unit,
                noise=noise, digits=digits, **limits)


MACHINE_METRICS = {
    "CNC_MILLING": [
        metric("Spindle_RotaryVelocity_RPM", "Tốc độ trục chính", 12000, "RPM", 15, 1),
        metric("Spindle_Load_Pct", "Tải động cơ", 45, "%", .3, 1, max=120),
        metric("Spindle_Temp_C", "Nhiệt độ trục chính", 38, "°C", .06, 2, max=75, critical_max=90),
        metric("Vibration_RMS_mm_s", "Độ rung RMS", 1.2, "mm/s", .03, 2, max=4.5, critical_max=7.1),
        metric("Coolant_Pressure_Bar", "Áp suất tưới nguội", 20, "Bar", .2, 1, min=5),
        metric("Tool_Wear_Pct", "Mòn dao", 12, "%", 0, 2, drift="+0.005 %/s"),
        metric("Path_Feedrate_Override_Pct", "Tốc độ ăn dao", 100, "%", 0, 0),
    ],
    "ROBOT_ARM": [
        metric("Joint_3_Current_A", "Dòng tải khớp 3", 9.25, "A", .05, 2, max=12.5, critical_max=16.5),
        metric("Motor_Temp_C", "Nhiệt động cơ khớp", 40, "°C", .04, 2, max=65, critical_max=80),
        metric("Gripper_Pressure_Bar", "Áp suất kẹp gắp", 6, "Bar", .08, 2, min=3.5),
        metric("Payload_Kg", "Tải trọng hiện tại", 3.5, "kg", 0, 2),
    ],
    "AMR_VEHICLE": [
        metric("Current_Velocity_m_s", "Vận tốc di chuyển", 1.2, "m/s", .02, 2),
        metric("Battery_Pct", "Dung lượng pin", 85, "%", .05, 2, min=25, critical_min=15, drift="−2.7333 %/phút"),
        metric("Battery_Temp_C", "Nhiệt độ pin", 33.6, "°C", .1, 1, max=55),
        metric("Lidar_Confidence_Pct", "Độ tin cậy LiDAR", 99.5, "%", .2, 1, min=65),
    ],
    "AOI_INSPECTION": [
        metric("False_Reject_Rate_Pct", "Tỷ lệ từ chối giả", .6, "%", .04, 2, max=2, critical_max=4),
        metric("Optics_Cleanliness_Pct", "Độ sạch kính", 99, "%", .1, 2, min=75),
        metric("Illumination_Intensity_Lux", "Cường độ sáng LED", 18500, "Lux", 15, 0, min=14000),
        metric("Conveyor_Speed_m_min", "Tốc độ băng chuyền", 1.2, "m/phút", .02, 2),
    ],
    "INJECTION_MOLDING": [
        metric("Nozzle_Temp_Zone1", "Nhiệt đầu phun vùng 1", 220, "°C", .12, 2, min=195, critical_max=245),
        metric("Clamping_Pressure_Bar", "Áp lực kẹp khuôn", 140, "Bar", .5, 1, min=115),
        metric("Injection_Pressure_Bar", "Áp suất phun nhựa", 95, "Bar", .5, 1, max=145),
    ],
}
