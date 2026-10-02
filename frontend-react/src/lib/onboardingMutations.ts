import {
  createManualCamera,
  type DiscoverySessionView,
  importOnvifDevice,
  importPersistedAnyway,
  inspectOnvif,
  refreshOnvifCapabilities,
  startDiscovery,
  testManualCamera,
  type CameraCreateInput,
  type OnvifImportInput,
  type OnvifInspectionView,
  type OnvifProbeInput,
} from "../api/onboarding"
import { CAMERA_ONBOARDING, CAMS } from "./queries"
import { useSave } from "./save"

/**
 * ## The probe-before-create ordering is ours, not the server's
 *
 * `POST /cameras` validates only `invalid_rtsp_url` syntax
 * (`cameras/service.py:104,112`) — it does not open the stream. The Vue wizard
 * called `/cameras/test` first as a client convention
 * (`CameraOnboardingPanel.vue:873-874`), and that convention is worth keeping:
 * creating a camera that cannot play is worse than a failed form.
 *
 * The two writes are therefore separate mutations, and the UI is responsible for
 * the ordering. Nothing here chains them automatically, because a chained write
 * that fails halfway leaves a camera nobody asked for.
 */

export function useStartDiscovery() {
  return useSave<string[], DiscoverySessionView>({
    // `variables` is the optional source-address list, not a camera id.
    mutationFn: (sourceAddresses) => startDiscovery(sourceAddresses ?? []),
    success: (data) => ({
      title: "发现完成",
      detail:
        data.candidates.length > 0
          ? `找到 ${data.candidates.length} 台设备。`
          : "没有找到设备。发现走的是 WS-Discovery 组播，只能看到同一广播域内的设备。",
    }),
    failure: (error) => ({
      title: "设备发现失败",
      detail: describeFailure(error),
    }),
  })
}

/**
 * A 10 s network call with a `SecretStr` password. Read-only, so it is safe to
 * run on an explicit click and never on a form blur.
 */
export function useInspectOnvif() {
  return useSave<OnvifProbeInput, OnvifInspectionView>({
    mutationFn: (body) => inspectOnvif(body),
    // A password never enters a query key, so there is nothing to invalidate
    // and nothing to leak into devtools history.
    success: () => ({ title: "设备检查完成" }),
    failure: (error) => ({ title: "设备检查失败", detail: describeFailure(error) }),
  })
}

/**
 * The write. Creates device + cameras + profiles + credential + endpoints.
 *
 * A 503 here means that graph already exists
 * (`details.configuration_persisted: true`, `api.py:893-904`) — the fourth
 * instance of this pattern. Retrying without thinking creates a duplicate
 * device, so the message says not to.
 */
export function useImportOnvifDevice() {
  return useSave<OnvifImportInput, unknown>({
    mutationFn: (body) => importOnvifDevice(body),
    invalidates: [CAMS.list(), CAMS.list(true), CAMERA_ONBOARDING.devices],
    success: () => ({
      title: "设备已导入",
      detail: "机位、码流与凭据已一并建立；运行时尚未对账，稍后会在机位列表中可见。",
    }),
    failure: (error) => {
      const persisted = importPersistedAnyway(error)
      if (persisted) {
        return {
          title: "设备已创建，但运行队列不可用",
          detail: `设备与机位已经落库（${persisted.deviceId ?? "未知 id"}），只是运行时尚未对账。请不要重复导入——重复导入会造出第二台同名设备。`,
        }
      }
      return { title: "导入失败", detail: describeFailure(error) }
    },
  })
}

export function useRefreshOnvifCapabilities(cameraId: string) {
  return useSave<void, unknown>({
    mutationFn: () => refreshOnvifCapabilities(cameraId),
    invalidates: [CAMS.list(), CAMS.list(true)],
    success: () => ({ title: "能力已重新读取" }),
    failure: (error) => ({ title: "重新读取失败", detail: describeFailure(error) }),
  })
}

export function useTestManualCamera() {
  return useSave<CameraCreateInput, unknown>({
    mutationFn: (body) => testManualCamera(body),
    success: () => ({ title: "连通性测试完成" }),
    failure: (error) => ({ title: "连通性测试失败", detail: describeFailure(error) }),
  })
}

export function useCreateManualCamera() {
  return useSave<CameraCreateInput, unknown>({
    mutationFn: (body) => createManualCamera(body),
    invalidates: [CAMS.list(), CAMS.list(true)],
    success: () => ({
      title: "机位已创建",
      // G-38: there is no field on CameraUpdate for a stream or credential, so
      // this is the only moment the operator can be told.
      detail:
        "RTSP 地址与密码之后无法在此修改。密码变更需要删除并重建该机位，" +
        "而删除会一并丢掉它上面的录制计划、录像保护与告警范围。",
    }),
    failure: (error) => ({ title: "创建机位失败", detail: describeFailure(error) }),
  })
}

function describeFailure(error: unknown): string {
  const code = (error as { code?: string } | null)?.code
  switch (code) {
    case "onvif_connection_failed":
      // Deliberately generic: wrong password, wrong IP and a firewall all land
      // here (`onvif_adapter.py:471-479`). Saying "wrong password" would be a
      // guess.
      return "无法连接该设备。地址、端口、凭据或网络策略任一不对，结果都一样，请逐项排查。"
    case "onvif_timeout":
      return "设备响应超时（服务端等待 10 秒）。"
    case "onvif_device_identity_conflict":
      return "该设备与本系统中已有设备身份冲突，无法新增。请先在机位列表中确认冲突记录。"
    case "onvif_device_identity_confirmation_required":
      return "疑似与已录入设备相同，需要先确认。"
    case "onvif_device_identity_confirmation_invalid":
      return "确认的设备与匹配结果不一致，请重新检查后再试。"
    case "onvif_device_already_exists":
      return "该 host:port 已属于另一台设备。"
    case "onvif_device_topology_changed":
      return "设备的码流结构在检查之后发生了变化，请重新检查。"
    case "onvif_no_usable_profiles":
      return "没有可用的码流：所有 profile 都取不到可用的流地址。"
    case "onvif_stream_uri_unavailable":
      return "该 profile 取不到可用的流地址。"
    case "invalid_onvif_profile_tokens":
      return "选中的 profile 不存在或已不可用。"
    case "onvif_discovery_failed":
      return "组播发现失败。请确认设备与本机在同一广播域，且没有被网络策略拦截。"
    case "onvif_discovery_source_address_invalid":
      return "指定的源地址不合法：必须是本机可用的非组播、非回环 IPv4，且最多 16 个。"
    case "invalid_rtsp_url":
      return "RTSP 地址无法解析，或协议不是 rtsp://。"
    case "discovery_candidate_mismatch":
      return "填写的地址与所选发现候选不一致。"
    case "device_credential_unavailable":
      return "密钥环里取不到该设备的凭据，密钥可能已被轮换掉。"
    default:
      return error instanceof Error ? error.message : String(error)
  }
}
