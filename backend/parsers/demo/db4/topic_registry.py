"""
parsers/demo/db4/topic_registry.py

DB4 所有 topic → proto 模块 + 消息类的完整映射。
数据来源：auto_receive.json + hdm_server.json 权威配置。

用法：
    from parsers.demo.db4.topic_registry import get_proto_class, IMAGE_TOPICS, UNKNOWN_TOPICS

    proto_cls = get_proto_class("SensorOdometry")  # → OdometryMsg class
    msg = proto_cls()
    msg.ParseFromArray(blob, len(blob))
"""

from __future__ import annotations
import sys
import os

# 将 proto 目录加入 sys.path（子进程启动时调用）
_PROTO_DIR = os.path.join(os.path.dirname(__file__), "proto")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

# ---------------------------------------------------------------------------
# 图像 topic（blob 是 H264/H265 码流，不解析 proto，存磁盘）
# ---------------------------------------------------------------------------
IMAGE_TOPICS: set[str] = {
    "EncodeFront", "EncodeFrontOriginal", "EncodeIPM",
    "EncodeSvcFront", "EncodeSvcLeft", "EncodeSvcRear", "EncodeSvcRight",
}

# ---------------------------------------------------------------------------
# 未知 topic（没有对应 proto，存原始 bytes）
# ---------------------------------------------------------------------------
UNKNOWN_TOPICS: set[str] = {
    "AlgDebugAeb", "AlgDebugIcc", "AlgDebugIhc",
    "AlgDebugLss", "AlgDebugPilotWrapper", "AlgDebugTsr",
    "CameraAlgStatus",          # proto 未找到
}

# ---------------------------------------------------------------------------
# 懒加载 proto class（避免启动时全量 import）
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, tuple[str, str]] = {
    # ── snoah 命名空间（Auto* 表）────────────────────────────────────────
    "AutoPose":                        ("onboard.proto.positioning_pb2",               "PoseProto"),
    "AutoSensorGnss":                  ("onboard.proto.positioning_pb2",               "GnssRawReadingProto"),
    "AutoSensorImu":                   ("onboard.proto.positioning_pb2",               "ImuRawReadingProto"),
    "AutoChassis":                     ("onboard.proto.chassis_pb2",                   "Chassis"),
    "AutoAutonomyState":               ("onboard.proto.autonomy_state_pb2",            "AutonomyStateProto"),
    "AutoGuardian":                    ("onboard.proto.autonomy_state_pb2",            "GuardianCmdProto"),
    "AutoDriverAction":                ("onboard.proto.autonomy_state_pb2",            "DriverAction"),
    "AutoParkHpaPsm":                  ("onboard.proto.autonomy_state_pb2",            "AutonomyStateProto"),
    "AutoTrajectory":                  ("onboard.proto.trajectory_pb2",                "TrajectoryProto"),
    "AutoParkTrajectory":              ("onboard.proto.trajectory_pb2",                "TrajectoryProto"),
    "AutoLocalizationTransform":       ("onboard.proto.localization_pb2",              "LocalizationTransformProto"),
    "AutoObjectsPrediction":           ("onboard.proto.prediction_pb2",                "ObjectsPredictionProto"),
    "AutoControlCommand":              ("onboard.proto.control_cmd_pb2",               "ControlCommand"),
    "AutoParkControlCommand":          ("onboard.proto.control_cmd_pb2",               "ControlCommand"),
    "AutoControllerDebug":             ("onboard.proto.control_cmd_pb2",               "ControllerDebugProto"),
    "AutoPlannerDebug":                ("onboard.proto.planner_pb2",                   "PlannerDebugProto"),
    "AutoQRunEvents":                  ("onboard.proto.q_run_events_pb2",              "QRunEventsProto"),
    "AutoParkQRunEvents":              ("onboard.proto.q_run_events_pb2",              "QRunEventsProto"),
    "AutoQRunEventStates":             ("onboard.proto.q_run_event_states_pb2",        "QRunEventStatesProto"),
    "AutoObstacles":                   ("onboard.proto.perception.fusion.objects_pb2", "ObjectsProto"),
    "AutoParkObstacles":               ("onboard.proto.perception.fusion.objects_pb2", "ObjectsProto"),
    "AutoFusedBevRoadGeometry":        ("onboard.proto.perception.fusion.fused_bev_road_geometry_pb2", "FusedBevRoadGeometryProto"),
    "AutoPlannerState":                ("onboard.planner.proto.planner_state_pb2",     "PlannerStateProto"),
    "AutoPlannerExternalCommandStatus":("onboard.planner.assist.proto.external_command_status_pb2", "PlannerExternalCommandStatusProto"),
    "AutoOnlineSemanticMap":           ("onboard.maps.proto.online_semantic_map_pb2",  "OnlineSemanticMapProto"),
    "AutoOnlineMap":                   ("onboard.proto.online_map_pb2",                "OnlineMapProto"),
    "AutoParkPose":                    ("onboard.proto.positioning_pb2",               "PoseProto"),
    "AutoParkChassis":                 ("onboard.proto.chassis_pb2",                   "Chassis"),
    "AutoParkAutonomyState":           ("onboard.proto.autonomy_state_pb2",            "AutonomyStateProto"),
    "AutoParkFusionFreespace":         ("onboard.proto.parking_spot_finder_pb2",       "FusionParkingFreespaceProto"),
    "AutoParkFusionSpots":             ("onboard.proto.parking_spot_finder_pb2",       "FusionParkingSpotsProto"),
    "AutoParkHmiState":                ("onboard.proto.parking_spot_finder_pb2",       "ParkHmiState"),
    "AutoParkCertifySlot":             ("onboard.proto.parking_spot_finder_pb2",       "ParkingSpotFinderProto"),
    "AutoRawNavigation":               ("onboard.proto.route_navigation_pb2",          "RawNavigationProto"),
    "AutoRouteManagerOutput":          ("onboard.proto.route_navigation_pb2",          "RouteManagerOutputProto"),
    "AutoSDRoute":                     ("onboard.proto.sd_map_route_pb2",              "SDRouteProto"),
    "AutoMppSections":                 ("onboard.proto.adasis_pb2",                    "MppSectionsProto"),
    "AutoEhpSpeedLimitRanges":         ("onboard.proto.adasis_pb2",                    "EhpSpeedLimitRangesProto"),
    "AutoMapRoadReminder":             ("onboard.proto.adasis_pb2",                    "MapRoadReminderProto"),

    # ── idrive 命名空间（非 Auto 表）────────────────────────────────────
    "SensorOdometry":                  ("interface.parking.odometry_pb2",              "OdometryMsg"),
    "Obstacle":                        ("interface.pilot.obstacles_pb2",               "ObstaclesMsg"),
    "Ped":                             ("interface.pilot.obstacles_pb2",               "ObstaclesMsg"),
    "Vehicle":                         ("interface.pilot.obstacles_pb2",               "ObstaclesMsg"),
    "BevObstacle":                     ("interface.pilot.obstacles_pb2",               "ObstaclesMsg"),
    "DiscObj":                         ("interface.pilot.objects_pb2",                 "ObjectsMsg"),
    "ObjectSign":                      ("interface.pilot.objects_pb2",                 "ObjectsMsg"),
    "ObjectLight":                     ("interface.pilot.objects_pb2",                 "ObjectsMsg"),
    "FusedStatic":                     ("interface.pilot.fused_static_pb2",            "FusedStaticMsg"),
    "Laneline":                        ("interface.pilot.laneline_pb2",                "LanelineMsg"),
    "LanelinePrim":                    ("interface.pilot.laneline_pb2",                "LanelineMsg"),  # MapEnv 类型，暂用 Laneline
    "Lane":                            ("interface.pilot.lanes_pb2",                   "LanesMsg"),
    "Parsing":                         ("interface.pilot.parsing_pb2",                 "ParsingMsg"),
    "LaneParsing":                     ("interface.pilot.parsing_pb2",                 "ParsingMsg"),
    "BevStatic":                       ("interface.pilot.bev_static_pb2",              "BevStaticMsg"),
    "Bev3D":                           ("interface.pilot.real3d_msg_pb2",              "Real3DMsg"),
    "ObstacleRaw":                     ("interface.pilot.real2d_msg_pb2",              "Real2DMsg"),
    "Radar":                           ("interface.pilot.radar_msg_pb2",               "RadarFrameMsg"),
    "PerceptionModuleTask":            ("interface.module_task_pb2",                   "ModuleTaskMsg"),
    "PerceptionTransact":              ("interface.transaction_pb2",                   "TransactionMsg"),
    "FusionTransact":                  ("interface.transaction_pb2",                   "TransactionMsg"),
    "PlanningTransact":                ("interface.transaction_pb2",                   "TransactionMsg"),
    "PostFusionTransact":              ("interface.transaction_pb2",                   "TransactionMsg"),
    "PsmTransact":                     ("interface.transaction_pb2",                   "TransactionMsg"),
    "VisionTransact":                  ("interface.transaction_pb2",                   "TransactionMsg"),
    "VehicleBody":                     ("interface.vehicle_body_pb2",                  "VehicleBodyMsg"),
    "VehicleChassis":                  ("interface.vehicle_chassis_pb2",               "VehicleChassisMsg"),
    "McuHeartBeat":                    ("interface.diag.mcu_heartbeat_pb2",            "McuHeartbeatMsg"),
    "FunctionState":                   ("interface.adas_function_pb2",                 "FunctionState"),
    "PilotFunction":                   ("interface.pilot.pilot_func_pb2",              "PilotFuncMsg"),
    "PilotControl":                    ("interface.parking.control_pb2",               "Control"),
    "Psm":                             ("interface.parking.psm_pb2",                   "PsmMsg"),
    "UssDistance":                     ("interface.parking.uss_distance_pb2",          "UssDistanceMsg"),
    "UssObstacles":                    ("interface.parking.uss_obstacles_pb2",         "UssObstaclesMsg"),
    "UssParkingSlots":                 ("interface.parking.uss_parking_slots_pb2",     "UssParkingSlotsMsg"),
    "UssSensorInfo":                   ("interface.parking.uss_sensor_info_pb2",       "UssSensorInfoMsg"),
    "SensorDynamicObstacles":          ("interface.parking.dynamic_obstacles_pb2",     "DynamicObstaclesMsg"),
    "HmiObstacleRaw":                  ("interface.parking.fusion_obstacle_pb2",       "FusionObstacleMsg"),
    "HmiSlotRaw":                      ("interface.parking.fusion_result_pb2",         "FusionParkingSlots"),
    "VersionInfo":                     ("interface.version_info_pb2",                  "VersionInfo"),
    "PilotVersionInfo":                ("interface.version_info_pb2",                  "VersionInfo"),
    "CameraStatus":                    ("model.camera_pb2",                            "CameraMsg"),
    "ParamCameraParam_prmsrvs_attr":   ("interface.params.camera_param_pb2",           "CameraParamMsg"),
    "ParamHmiParams_prmsrvs_attr":     ("interface.parking.hmi_pad_event_pb2",         "UserEventMsg"),
    "ParamProjectConfigParam_prmsrvs_attr": ("interface.parking.project_config_param_pb2", "ProjectConfig"),
    "ParamVehicleParam_prmsrvs_attr":  ("interface.params.vehicle_param_pb2",          "VehicleParam"),
    "TrafficLightMin":                 ("idrive.simple.traffic_sign_min_pb2",          "TrafficSignMinMsg"),
    "TrafficSignMin":                  ("idrive.simple.traffic_sign_min_pb2",          "TrafficSignMinMsg"),
    "DiagInfo":                        ("idrive.interface.diag.diag_info_pb2",         "DiagInfoMsg"),
    "SensorParkingSystem":             ("interface.parking.parking_system_pb2",         "ParkingSystemMsg"),
    "SystemInfo":                      ("idrive.interface.system_info_pb2",            "SystemInfoMsg"),
    "LaneMin":                         ("idrive.simple.lane_min_pb2",                  "LaneMinMsg"),
    "ObstacleMin":                     ("idrive.simple.obstacle_min_pb2",              "ObstacleMinMsg"),
    "Tsm":                             ("idrive.model.tsm_pb2",                        "TsmMsg"),
    "TsmToApp":                        ("idrive.model.tsm_to_app_cmd_pb2",             "TsmToAppCmdMsg"),
    "TimeSyncToSoc":                   ("idrive.service.time_sync_pb2",                "TimeSyncMsg"),

    # Camera（图像）表通过 IMAGE_TOPICS 集合处理，此处亦保留 proto 元信息
    "EncodeFront":                     ("model.camera_pb2",                            "CameraMsg"),
    "EncodeFrontOriginal":             ("model.camera_pb2",                            "CameraMsg"),
    "EncodeIPM":                       ("model.camera_pb2",                            "CameraMsg"),
    "EncodeSvcFront":                  ("model.camera_pb2",                            "CameraMsg"),
    "EncodeSvcLeft":                   ("model.camera_pb2",                            "CameraMsg"),
    "EncodeSvcRear":                   ("model.camera_pb2",                            "CameraMsg"),
    "EncodeSvcRight":                  ("model.camera_pb2",                            "CameraMsg"),
}

# ---------------------------------------------------------------------------
# 运行时查找 proto class
# ---------------------------------------------------------------------------
_cache: dict[str, type] = {}

# idrive 的依赖需要先 import common_msg 才能解析其他模块
def _preload_idrive_common():
    try:
        from idrive.common import common_msg_pb2  # noqa: F401
    except Exception:
        pass

_preload_idrive_common()


def get_proto_class(topic: str):
    """
    返回 topic 对应的 proto message 类。
    找不到返回 None（调用方按 raw bytes 处理）。
    """
    if topic in _cache:
        return _cache[topic]

    entry = _REGISTRY.get(topic)
    if entry is None:
        return None

    module_path, class_name = entry
    try:
        mod = __import__(module_path, fromlist=[class_name])
        cls = getattr(mod, class_name)
        _cache[topic] = cls
        return cls
    except Exception:
        return None


def all_topics() -> list[str]:
    """返回所有已知 topic 名称。"""
    return list(_REGISTRY.keys())
