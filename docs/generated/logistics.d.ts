/**
 * ÜRETİLMİŞ DOSYA — elle düzenlemeyin.
 * Kaynak: tradehub_core Python sözleşmesi
 * Yeniden üret: python3 scripts/gen_logistics_types.py --sync
 */

// ── Yanıt zarfı ──
export interface LogisticsOk<T> { ok: true; data: T }
export interface LogisticsErr {
  ok: false;
  error: { code: LogisticsErrorCode; message: string; details?: Record<string, unknown> };
}
export type LogisticsResponse<T> = LogisticsOk<T> | LogisticsErr;

export interface CatalogPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ── Hata kodları ──
export type LogisticsErrorCode =
  | "CAPABILITY_REQUIRED"
  | "CARRIER_API_ERROR"
  | "CARRIER_CAPABILITY_UNSUPPORTED"
  | "CARRIER_NOT_FOUND"
  | "CARRIER_TIMEOUT"
  | "DUPLICATE_ENTRY"
  | "FEATURE_DISABLED"
  | "IDEMPOTENCY_CONFLICT"
  | "INTERNAL_ERROR"
  | "LOGISTICS_ERROR"
  | "NOT_FOUND"
  | "PERMISSION_DENIED"
  | "SHIPMENT_STATE_INVALID"
  | "SPLIT_INVARIANT_VIOLATION"
  | "TRACKING_NOT_FOUND"
  | "VALIDATION_ERROR"
  ;

// Kod -> HTTP durumu eşlemesi bilinçli olarak BURADA DEĞİL: .d.ts bir
// bildirim dosyasıdır ve değer içeremez (TS1039). Eşleme gerekiyorsa
// docs/logistics-api.schema.json içindeki error_codes bölümünü kullan;
// zaten HTTP durumu yanıtın kendisinde de geliyor.

// ── Enum'lar ──
export type ShipmentStatus = "Draft" | "Pending" | "Ready for Pickup" | "Picked Up" | "In Transit" | "At Warehouse" | "Out for Delivery" | "Delivered" | "Returned" | "Cancelled" | "Failed";
export type ShipmentType = "Standard" | "Seller Delivery" | "Buyer Pickup" | "Warehouse Transfer";
export type LegType = "Pickup" | "Line Haul" | "Transfer" | "Last Mile" | "Return";
export type LegStatus = "Planned" | "In Progress" | "Arrived" | "Completed" | "Cancelled";
export type CostPaidBy = "Seller" | "Buyer" | "Platform";
export type TerminalStatus = "Cancelled" | "Delivered" | "Returned";
export type FeatureFlag = "auto_tracking_enabled" | "buyer_pickup_enabled" | "carrier_api_enabled" | "cost_estimation_enabled" | "multi_carrier_enabled" | "multi_leg_enabled" | "return_flow_enabled" | "seller_delivery_enabled" | "shipping_zone_pricing_enabled" | "split_shipment_enabled" | "warehouse_transfer_enabled" | "webhook_notifications_enabled";

// ── Kataloglar ──
export interface ShippingChannelListItem {
  name: string;
  channel_name: string;
  channel_code: string;
  is_active?: number;
}

export interface ShippingChannelDetail extends ShippingChannelListItem {
  icon?: string;
  description?: string;
}

export interface ShippingMethodListItem {
  name: string;
  method_name: string;
  shipping_type?: string;  // Express | Air | Sea | Land | Standard
  channel?: string;  // -> Shipping Channel
  is_active?: number;
  min_days?: number;
  max_days?: number;
  base_cost?: number;
  currency?: string;  // -> Currency
}

export interface ShippingMethodCarrierServicesRow {
  carrier_service: string;  // -> Carrier Service
  service_name?: string;
  is_preferred?: number;
  priority?: number;
}

export interface ShippingMethodDetail extends ShippingMethodListItem {
  max_weight?: number;
  max_desi?: number;
  cost_per_kg?: number;
  free_shipping_threshold?: number;
  description?: string;
  carrier_services: ShippingMethodCarrierServicesRow[];
}

export interface LogisticsProviderListItem {
  name: string;
  provider_name: string;
  provider_code: string;
  provider_type?: string;  // Kargo | Ambar | Kurye | Marketplace
  integration_type?: string;  // API | Manual | Webhook
  country?: string;  // -> Country
  is_active?: number;
}

export interface LogisticsProviderOperatingChannelsRow {
  shipping_channel: string;  // -> Shipping Channel
  channel_name?: string;
}

export interface LogisticsProviderDetail extends LogisticsProviderListItem {
  logo?: string;
  website?: string;
  support_phone?: string;
  support_email?: string;
  operating_channels: LogisticsProviderOperatingChannelsRow[];
}

export interface CarrierServiceListItem {
  name: string;
  service_name: string;
  service_code: string;
  carrier: string;  // -> Logistics Provider
  service_type?: string;  // Standard | Express | Economy | Same Day | Scheduled
  is_active?: number;
}

export interface CarrierServiceDetail extends CarrierServiceListItem {
  max_weight?: number;
  max_desi?: number;
  estimated_days_min?: number;
  estimated_days_max?: number;
  supports_cod?: number;
  supports_insurance?: number;
}

export interface CarrierBranchListItem {
  name: string;
  branch_name: string;
  branch_code: string;
  carrier: string;  // -> Logistics Provider
  branch_type?: string;  // Hub | Transfer Center | Distribution Point | Service Point | Locker
  city?: string;
  district?: string;
  is_active?: number;
}

export interface CarrierBranchDetail extends CarrierBranchListItem {
  postal_code?: string;
  address?: string;
  phone?: string;
  latitude?: number;
  longitude?: number;
  operating_hours?: Record<string, unknown> | null;
}

export interface ServiceCoverageAreaListItem {
  name: string;
  carrier: string;  // -> Logistics Provider
  carrier_service?: string;  // -> Carrier Service
  city: string;
  district?: string;
  is_active?: number;
}

export interface ServiceCoverageAreaDetail extends ServiceCoverageAreaListItem {
  postal_code_from?: string;
  postal_code_to?: string;
  estimated_days_override?: number;
}

export interface CarrierStatusMappingListItem {
  name: string;
  carrier: string;  // -> Logistics Provider
  carrier_status_code: string;
  carrier_status_text?: string;
  internal_status: string;  // Draft | Pending | Ready for Pickup | Picked Up | In Transit | At Warehouse | Out for Delivery | Delivered | Returned | Cancelled | Failed
  exception_code?: string;  // -> Shipment Exception Code
}

export type CarrierStatusMappingDetail = CarrierStatusMappingListItem;

export interface PackageTypeListItem {
  name: string;
  package_name: string;
  package_code: string;
  is_default?: number;
  is_active?: number;
  max_weight_kg?: number;
}

export interface PackageTypeDetail extends PackageTypeListItem {
  max_length_cm?: number;
  max_width_cm?: number;
  max_height_cm?: number;
  max_desi?: number;
  description?: string;
}

export interface VehicleTypeListItem {
  name: string;
  vehicle_name: string;
  vehicle_code: string;
  vehicle_category?: string;  // Motokurye | Panelvan | Kamyonet | Kamyon | TIR
  is_active?: number;
  max_weight_kg?: number;
}

export interface VehicleTypeDetail extends VehicleTypeListItem {
  max_volume_m3?: number;
  max_desi?: number;
  description?: string;
}

export interface ShipmentExceptionCodeListItem {
  name: string;
  exception_name: string;
  exception_code: string;
  exception_category?: string;  // Address | Recipient | Package | Customs | Weather | Other
  severity?: string;  // Info | Warning | Critical
  is_retriable?: number;
}

export interface ShipmentExceptionCodeDetail extends ShipmentExceptionCodeListItem {
  description?: string;
  suggested_action?: string;
}

// ── Taşıyıcı hesabı ──
export interface CarrierAccount {
  name: string;
  account_name: string;
  carrier: string;  // -> Logistics Provider
  seller_profile?: string;  // -> Admin Seller Profile
  environment?: string;  // Production | Sandbox
  is_active?: number;
  is_default?: number;
  base_url?: string;
  token_expiry?: string;
  is_platform_account: boolean;
  has_api_key: boolean;
  has_api_secret: boolean;
  has_webhook_secret: boolean;
  has_access_token: boolean;
}

/** Gizli alan DEĞERLERİ liste/detay yanıtında dönmez; reveal_carrier_secret ile alınır. */
export type CarrierSecretField = "api_key" | "api_secret" | "webhook_secret" | "access_token";

// ── Ayarlar ──
export interface LogisticsSettings {
  logistics_enabled?: number;
  auto_tracking_enabled?: number;
  tracking_poll_interval_minutes?: number;
  sla_breach_notify_hours?: number;
  default_currency?: string;  // -> Currency
  shipment_naming_series?: string;
  default_logistics_provider?: string;  // -> Logistics Provider
  default_package_type?: string;  // -> Package Type
  default_vehicle_type?: string;  // -> Vehicle Type
  auto_assign_carrier?: number;
  max_delivery_attempts?: number;
  return_window_days?: number;
}

export type LogisticsFeatureFlags = Record<FeatureFlag, boolean>;

// ── Yetki bildirimi ──
export interface LogisticsPermissions {
  user: string;
  capabilities: Record<LogisticsCapability, boolean>;
  roles: Record<string, boolean>;
  doctype_permissions: Record<string, { read: boolean; write: boolean; create: boolean; delete: boolean }>;
  module_enabled: boolean;
}
export type LogisticsCapability = "shipment.create" | "shipment.write" | "shipment.cancel" | "shipment.split" | "view.logistics_cost" | "view.tracking" | "carrier_credential.manage" | "view.carrier_secret";

