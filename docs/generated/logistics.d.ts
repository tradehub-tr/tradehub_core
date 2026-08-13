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

// ── Sevkiyat ve ilgili varlıklar (GEÇİCİ SÖZLEŞME) ──
// DocType'ları henüz yok; alanlar logistics/contract.py'de beyan edildi.
// Faz F backend'i bu sözleşmeye implement edecek.
/** Sevkiyat — kaynak: TUR-105, TUR-106, TUR-107 */
export interface ShipmentListItem {
  name: string;
  order: string;
  seller_profile: string;
  buyer?: string;
  status: string;
  shipment_type: string;
  channel?: string;
  carrier?: string;
  carrier_service?: string;
  tracking_number?: string;
  package_count?: number;
  chargeable_weight?: number;
  ship_date?: string;
  estimated_delivery?: string;
  actual_delivery?: string;
  is_delayed?: number;
  modified?: string;
}

export interface ShipmentAddressSnapshotsRow {
  snapshot_type: string;
  source_address?: string;
  contact_name?: string;
  company?: string;
  phone_prefix?: string;
  phone?: string;
  country?: string;
  state?: string;
  city?: string;
  street?: string;
  apartment?: string;
  postal_code?: string;
  tax_no?: string;
  tax_office?: string;
}

export interface ShipmentItemsRow {
  item: string;
  item_name: string;
  ordered_qty: number;
  shipped_qty: number;
  remaining_qty?: number;
  uom?: string;
  weight_kg?: number;
  returned_qty?: number;
}

export interface ShipmentPackagesRow {
  package_code: string;
  sequence_label: string;
  package_type?: string;
  parent_package?: string;
  length_cm?: number;
  width_cm?: number;
  height_cm?: number;
  weight_kg?: number;
  desi?: number;
  barcode_url?: string;
  label_url?: string;
  label_printed_at?: string;
}

export interface ShipmentLegsRow {
  sequence: number;
  leg_type: string;
  status: string;
  carrier?: string;
  origin_branch?: string;
  destination_branch?: string;
  handover_point?: string;
  handover_proof?: string;
  vehicle_type?: string;
  started_at?: string;
  completed_at?: string;
  cost?: number;
}

export interface ShipmentEventsRow {
  event_time: string;
  status: string;
  source: string;
  carrier_status_code?: string;
  carrier_status_text?: string;
  location?: string;
  description?: string;
  exception_code?: string;
  actor?: string;
  reason?: string;
  dedupe_key?: string;
}

export interface ShipmentDetail extends ShipmentListItem {
  warehouse?: string;
  total_weight?: number;
  total_desi?: number;
  cost_paid_by?: string;
  carrier_cost?: number;
  customer_charge?: number;
  currency?: string;
  exception_code?: string;
  delivery_code_required?: number;
  payment_required_before_delivery?: number;
  seller_note?: string;
  buyer_note?: string;
  internal_note?: string;
  driver_name?: string;
  driver_phone?: string;
  vehicle_plate?: string;
  appointment_at?: string;
  appointment_window?: string;
  delivery_code_status?: string;
  delivery_code_attempts?: number;
  pickup_location?: string;
  payment_status?: string;
  address_snapshots: ShipmentAddressSnapshotsRow[];
  items: ShipmentItemsRow[];
  packages: ShipmentPackagesRow[];
  legs: ShipmentLegsRow[];
  events: ShipmentEventsRow[];
}

/** Teslim Kanıtı — kaynak: TUR-115 */
export interface ProofOfDeliveryListItem {
  delivered_at: string;
  received_by: string;
  delivery_code_used?: number;
  signature_url?: string;
  photo_url?: string;
  document_url?: string;
  location_source?: string;
  location_recorded_at?: string;
}

export type ProofOfDeliveryDetail = ProofOfDeliveryListItem;

/** İade Talebi — kaynak: TUR-116 */
export interface ReturnRequestListItem {
  name: string;
  order: string;
  shipment?: string;
  seller_profile: string;
  buyer: string;
  status: string;
  reason: string;
  requested_at: string;
  decided_at?: string;
  is_closed?: number;
}

export interface ReturnRequestItemsRow {
  item: string;
  item_name: string;
  requested_qty: number;
  received_qty?: number;
  accepted_qty?: number;
  uom?: string;
  inspection_result?: string;
  inspection_note?: string;
  unit_refund?: number;
}

export interface ReturnRequestDetail extends ReturnRequestListItem {
  decision_note?: string;
  return_shipment?: string;
  return_label_url?: string;
  inspection_result?: string;
  inspection_note?: string;
  refund_amount?: number;
  refund_triggered_at?: string;
  exchange_shipment?: string;
  closed_at?: string;
  closed_by?: string;
  items: ReturnRequestItemsRow[];
}

/** Fiyat Teklifi — kaynak: TUR-121 */
export interface PriceQuoteListItem {
  quote_id: string;
  carrier: string;
  carrier_service?: string;
  carrier_cost: number;
  customer_charge: number;
  currency: string;
  chargeable_weight?: number;
  applied_rule?: string;
  rule_priority?: number;
  valid_until?: string;
  is_snapshot?: number;
  surcharges?: Record<string, unknown> | null;
}

export type PriceQuoteDetail = PriceQuoteListItem;

/** Bağlantı Testi Sonucu — kaynak: TUR-110, TUR-111 */
export interface ConnectionTestListItem {
  carrier_account: string;
  probe: string;
  succeeded: number;
  http_status?: number;
  duration_ms?: number;
  message?: string;
  error_code?: string;
  tested_at: string;
  tested_by?: string;
}

export type ConnectionTestDetail = ConnectionTestListItem;

/** Entegrasyon Logu — kaynak: TUR-110 */
export interface IntegrationLogListItem {
  name: string;
  carrier: string;
  carrier_account?: string;
  operation: string;
  direction: string;
  shipment?: string;
  succeeded: number;
  http_status?: number;
  duration_ms?: number;
  attempt?: number;
  error_code?: string;
  error_message?: string;
  request_body?: unknown;
  response_body?: unknown;
  is_retriable?: number;
  created_at: string;
}

export type IntegrationLogDetail = IntegrationLogListItem;

/** Palet Planı — kaynak: TUR-120 */
export interface PalletPlanListItem {
  name: string;
  shipment: string;
  pallet_code: string;
  pallet_type?: string;
  layer_count?: number;
  max_layers?: number;
  package_count?: number;
  loaded_weight_kg?: number;
  max_weight_kg?: number;
  loaded_desi?: number;
  is_overloaded?: number;
}

export type PalletPlanDetail = PalletPlanListItem;

/** Toplu İçe Aktarma — kaynak: TUR-107 */
export interface ImportJobListItem {
  name: string;
  file_name: string;
  status: string;
  total_rows: number;
  valid_rows?: number;
  error_rows?: number;
  applied_rows?: number;
  column_mapping?: Record<string, unknown> | null;
  errors?: Record<string, unknown> | null;
  created_at: string;
  created_by?: string;
}

export type ImportJobDetail = ImportJobListItem;

/** Bildirim Şablonu — kaynak: TUR-113 */
export interface NotificationTemplateListItem {
  name: string;
  event: string;
  channel: string;
  recipient_role: string;
  subject?: string;
  body?: string;
  is_active?: number;
  is_mandatory?: number;
}

export type NotificationTemplateDetail = NotificationTemplateListItem;

/** Bildirim Tercihi — kaynak: TUR-113 */
export interface NotificationPreferenceListItem {
  template: string;
  event: string;
  channel: string;
  recipient_role: string;
  enabled: number;
  is_mandatory?: number;
  locked_reason?: string;
}

export type NotificationPreferenceDetail = NotificationPreferenceListItem;

/** Operasyon Alarmı — kaynak: TUR-113 */
export interface OperationAlertListItem {
  name: string;
  alert_type: string;
  severity: string;
  title: string;
  detail?: string;
  shipment?: string;
  carrier?: string;
  affected_count?: number;
  raised_at: string;
  acknowledged_at?: string;
  acknowledged_by?: string;
}

export type OperationAlertDetail = OperationAlertListItem;

/** Fiyatlandırma Kuralı — kaynak: TUR-121 */
export interface PricingRuleListItem {
  name: string;
  rule_name: string;
  carrier?: string;
  carrier_service?: string;
  shipping_method?: string;
  priority: number;
  is_active?: number;
  min_desi?: number;
  max_desi?: number;
  min_weight_kg?: number;
  max_weight_kg?: number;
  origin_city?: string;
  destination_city?: string;
  zone?: string;
  min_order_total?: number;
  base_cost?: number;
  base_charge?: number;
  per_desi_charge?: number;
  currency?: string;
  valid_from?: string;
  valid_until?: string;
}

export type PricingRuleDetail = PricingRuleListItem;

/** Performans Raporu — kaynak: TUR-118 */
export interface PerformanceReportListItem {
  dimension: string;
  dimension_label: string;
  shipment_count: number;
  delivered_count?: number;
  delayed_count?: number;
  failed_count?: number;
  returned_count?: number;
  avg_delivery_days?: number;
  p90_delivery_days?: number;
  on_time_rate?: number;
  failure_rate?: number;
  return_rate?: number;
}

export type PerformanceReportDetail = PerformanceReportListItem;

/** Maliyet Raporu — kaynak: TUR-118, TUR-121 */
export interface CostReportListItem {
  dimension: string;
  dimension_label: string;
  shipment_count: number;
  carrier_cost_total: number;
  customer_charge_total: number;
  margin_total: number;
  margin_rate?: number;
  avg_cost_per_shipment?: number;
  currency: string;
}

export type CostReportDetail = CostReportListItem;

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

