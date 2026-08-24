-- T-044 · media_engine/doctype_specs/*.json dosyalarindan URETILDI.
-- Bu dosya BIR MIGRATION DEGILDIR: DocType'lar Frappe'ye kurulmadi (Faz 4 karari).
-- Amaci indeks planinin kurulabilirligini kanitlamak ve EXPLAIN provalari icin
-- gecici bir sema kurabilmektir.

drop table if exists `tabMedia Asset`;
create table `tabMedia Asset` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `slot_key` varchar(140) DEFAULT NULL,
  `owner_seller` varchar(140) DEFAULT NULL,
  `media_type` varchar(140) DEFAULT NULL,
  `state` varchar(140) DEFAULT NULL,
  `content_sha256` varchar(64) DEFAULT NULL,
  `perceptual_hash` varchar(32) DEFAULT NULL,
  `active_version` varchar(140) DEFAULT NULL,
  `source` varchar(140) DEFAULT NULL,
  `legal_hold` int(1) NOT NULL DEFAULT 0,
  `published_at` datetime DEFAULT NULL,
  `last_access_at` datetime DEFAULT NULL,
  `rejection_code` varchar(140) DEFAULT NULL,
  `rejection_note` text DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_slot_key` (`slot_key`),
  KEY `ix_owner_seller` (`owner_seller`),
  KEY `ix_state` (`state`),
  UNIQUE KEY `uk_content_sha256` (`content_sha256`),
  KEY `ix_perceptual_hash` (`perceptual_hash`),
  KEY `ix_last_access_at` (`last_access_at`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;

alter table `tabMedia Asset` add key `ix_seller_state_modified` (`owner_seller`,`state`,`modified`);
alter table `tabMedia Asset` add key `ix_state_lastaccess` (`state`,`last_access_at`);
alter table `tabMedia Asset` add key `ix_state_hold_creation` (`state`,`legal_hold`,`creation`);

drop table if exists `tabMedia Content Rule`;
create table `tabMedia Content Rule` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `parent` varchar(140) DEFAULT NULL,
  `parentfield` varchar(140) DEFAULT NULL,
  `parenttype` varchar(140) DEFAULT NULL,
  `rule_id` varchar(64) DEFAULT NULL,
  `metric` varchar(64) DEFAULT NULL,
  `comparator` varchar(140) DEFAULT NULL,
  `threshold` varchar(140) DEFAULT NULL,
  `severity` varchar(140) DEFAULT NULL,
  `message_key` varchar(64) DEFAULT NULL,
  `measured_on` varchar(140) DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_parent` (`parent`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;


drop table if exists `tabMedia Crop Intent`;
create table `tabMedia Crop Intent` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `asset` varchar(140) DEFAULT NULL,
  `focal_x` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `focal_y` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `safe_x` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `safe_y` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `safe_w` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `safe_h` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `method` varchar(140) DEFAULT NULL,
  `algorithm` varchar(64) DEFAULT NULL,
  `algorithm_version` varchar(32) DEFAULT NULL,
  `confidence` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `approved_by_user` int(1) NOT NULL DEFAULT 0,
  `previewed_placements` longtext DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  UNIQUE KEY `uk_asset` (`asset`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;


drop table if exists `tabMedia Crop Override`;
create table `tabMedia Crop Override` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `parent` varchar(140) DEFAULT NULL,
  `parentfield` varchar(140) DEFAULT NULL,
  `parenttype` varchar(140) DEFAULT NULL,
  `profile` varchar(140) DEFAULT NULL,
  `x` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `y` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `w` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `h` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `method` varchar(140) DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_parent` (`parent`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;


-- Media Engine Settings: Single DocType — tablosu yok (tabSingles).
drop table if exists `tabMedia Policy`;
create table `tabMedia Policy` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `slot_key` varchar(64) DEFAULT NULL,
  `title` varchar(140) DEFAULT NULL,
  `schema_version` varchar(16) DEFAULT NULL,
  `status` varchar(140) DEFAULT NULL,
  `roles` longtext DEFAULT NULL,
  `accept` longtext DEFAULT NULL,
  `require` longtext DEFAULT NULL,
  `master` longtext DEFAULT NULL,
  `quality` longtext DEFAULT NULL,
  `on_violation` longtext DEFAULT NULL,
  `messages` longtext DEFAULT NULL,
  `sources` longtext DEFAULT NULL,
  `source_file` varchar(200) DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  UNIQUE KEY `uk_slot_key` (`slot_key`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;


drop table if exists `tabMedia Policy Profile`;
create table `tabMedia Policy Profile` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `parent` varchar(140) DEFAULT NULL,
  `parentfield` varchar(140) DEFAULT NULL,
  `parenttype` varchar(140) DEFAULT NULL,
  `profile` varchar(140) DEFAULT NULL,
  `required` int(1) NOT NULL DEFAULT 0,
  `generation` varchar(140) DEFAULT NULL,
  `max_bytes` int(11) NOT NULL DEFAULT 0,
  `byte_reference` varchar(140) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_parent` (`parent`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;


drop table if exists `tabMedia Processing Job`;
create table `tabMedia Processing Job` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `asset` varchar(140) DEFAULT NULL,
  `job_type` varchar(140) DEFAULT NULL,
  `queue` varchar(140) DEFAULT NULL,
  `status` varchar(140) DEFAULT NULL,
  `attempt` int(11) NOT NULL DEFAULT 0,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `duration_ms` int(11) NOT NULL DEFAULT 0,
  `peak_memory_mb` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `error_code` varchar(64) DEFAULT NULL,
  `error_trace` longtext DEFAULT NULL,
  `idempotency_key` varchar(140) DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_asset` (`asset`),
  KEY `ix_status` (`status`),
  UNIQUE KEY `uk_idempotency_key` (`idempotency_key`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;

alter table `tabMedia Processing Job` add key `ix_queue_status` (`queue`,`status`);

drop table if exists `tabMedia Profile`;
create table `tabMedia Profile` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `profile_key` varchar(64) DEFAULT NULL,
  `label` varchar(100) DEFAULT NULL,
  `aspect_ratio` varchar(16) DEFAULT NULL,
  `aspect_ratio_value` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `widths` longtext DEFAULT NULL,
  `formats` longtext DEFAULT NULL,
  `fit` varchar(140) DEFAULT NULL,
  `quality_target` int(11) NOT NULL DEFAULT 0,
  `generation` varchar(140) DEFAULT NULL,
  `enabled` int(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  UNIQUE KEY `uk_profile_key` (`profile_key`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;


drop table if exists `tabMedia Quality Report`;
create table `tabMedia Quality Report` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `report_type` varchar(140) NOT NULL DEFAULT 'asset',
  `asset` varchar(140) DEFAULT NULL,
  `version` varchar(140) DEFAULT NULL,
  `slot` varchar(140) DEFAULT NULL,
  `engine_version` varchar(140) DEFAULT NULL,
  `period_key` varchar(140) DEFAULT NULL,
  `period_start` date DEFAULT NULL,
	  `period_end` date DEFAULT NULL,
	  `processed_assets` bigint(20) NOT NULL DEFAULT 0,
	  `total_job_count` bigint(20) NOT NULL DEFAULT 0,
	  `failure_count` bigint(20) NOT NULL DEFAULT 0,
  `failure_rate` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `input_bytes` bigint(20) NOT NULL DEFAULT 0,
  `output_bytes` bigint(20) NOT NULL DEFAULT 0,
  `saved_bytes` bigint(20) NOT NULL DEFAULT 0,
  `saving_ratio` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `saved_gb` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `ssim` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `vmaf` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `ssim_by_profile` longtext DEFAULT NULL,
  `average_processing_ms` decimal(21,9) DEFAULT NULL,
  `average_lcp_impact_ms` decimal(21,9) DEFAULT NULL,
  `decisions` longtext DEFAULT NULL,
  `warnings` longtext DEFAULT NULL,
  `slot_distribution` longtext DEFAULT NULL,
  `worst_assets` longtext DEFAULT NULL,
  `summary_tr` text DEFAULT NULL,
  `markdown` longtext DEFAULT NULL,
  `report_json` longtext DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_asset` (`asset`),
  KEY `ix_version` (`version`),
  UNIQUE KEY `uk_period_key` (`period_key`),
  KEY `ix_period` (`report_type`, `period_start`, `period_end`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;


drop table if exists `tabMedia Rendition`;
create table `tabMedia Rendition` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `version` varchar(140) DEFAULT NULL,
  `profile` varchar(140) DEFAULT NULL,
  `width` int(11) NOT NULL DEFAULT 0,
  `height` int(11) NOT NULL DEFAULT 0,
  `format` varchar(140) DEFAULT NULL,
  `rendition_key` varchar(180) DEFAULT NULL,
  `bytes` int(11) NOT NULL DEFAULT 0,
  `quality` int(11) NOT NULL DEFAULT 0,
  `ssim` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `file_url` varchar(500) DEFAULT NULL,
  `storage_backend` varchar(140) DEFAULT NULL,
  `generation` varchar(140) DEFAULT NULL,
  `last_access_at` datetime DEFAULT NULL,
  `benefit_gate_passed` int(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_last_access_at` (`last_access_at`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;

-- Bilesik UNIQUE: Frappe DocType JSON bunu ifade edemez, bu yuzden ham DDL ile
-- (after_migrate kancasi) kurulur. T-044 §4.3'te OLCULDU: turetilmis alani
-- (rendition_key/usage_key) AYRICA unique yapmak ayni kisiti iki kez odetiyor.
-- Bu indeks ayni zamanda ilk kolon(lar) uzerinden arama yolunu da karsilar.
alter table `tabMedia Rendition` add unique key `uk_rendition_quad` (`version`,`profile`,`width`,`format`);

drop table if exists `tabMedia Source`;
create table `tabMedia Source` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `asset` varchar(140) DEFAULT NULL,
  `file_url` varchar(500) DEFAULT NULL,
  `storage_backend` varchar(140) DEFAULT NULL,
  `bytes` int(11) NOT NULL DEFAULT 0,
  `mime_real` varchar(100) DEFAULT NULL,
  `mime_claimed` varchar(100) DEFAULT NULL,
  `width` int(11) NOT NULL DEFAULT 0,
  `height` int(11) NOT NULL DEFAULT 0,
  `megapixels` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `dpi_x` int(11) NOT NULL DEFAULT 0,
  `dpi_y` int(11) NOT NULL DEFAULT 0,
  `colorspace` varchar(32) DEFAULT NULL,
  `has_alpha` int(1) NOT NULL DEFAULT 0,
  `frames` int(11) NOT NULL DEFAULT 0,
  `duration` decimal(21,9) NOT NULL DEFAULT 0.000000000,
  `video_codec` varchar(32) DEFAULT NULL,
  `audio_codec` varchar(32) DEFAULT NULL,
  `bitrate` int(11) NOT NULL DEFAULT 0,
  `exif_stripped` int(1) NOT NULL DEFAULT 0,
  `uploaded_by` varchar(140) DEFAULT NULL,
  `client_report` longtext DEFAULT NULL,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_asset` (`asset`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;


-- Media Storage Settings: Single DocType — tablosu yok (tabSingles).
drop table if exists `tabMedia Usage`;
create table `tabMedia Usage` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `asset` varchar(140) DEFAULT NULL,
  `ref_doctype` varchar(140) DEFAULT NULL,
  `ref_name` varchar(140) DEFAULT NULL,
  `ref_field` varchar(140) DEFAULT NULL,
  `usage_key` varchar(180) DEFAULT NULL,
  `profile_used` varchar(140) DEFAULT NULL,
  `first_seen` datetime DEFAULT NULL,
  `last_seen` datetime DEFAULT NULL,
  `is_open` int(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_last_seen` (`last_seen`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;

alter table `tabMedia Usage` add key `ix_asset_open` (`asset`,`is_open`);
alter table `tabMedia Usage` add key `ix_ref` (`ref_doctype`,`ref_name`);
-- Bilesik UNIQUE: Frappe DocType JSON bunu ifade edemez, bu yuzden ham DDL ile
-- (after_migrate kancasi) kurulur. T-044 §4.3'te OLCULDU: turetilmis alani
-- (rendition_key/usage_key) AYRICA unique yapmak ayni kisiti iki kez odetiyor.
-- Bu indeks ayni zamanda ilk kolon(lar) uzerinden arama yolunu da karsilar.
alter table `tabMedia Usage` add unique key `uk_usage_quad` (`asset`,`ref_doctype`,`ref_name`,`ref_field`);

drop table if exists `tabMedia Version`;
create table `tabMedia Version` (
  `name` varchar(140) NOT NULL,
  `creation` datetime(6) DEFAULT NULL,
  `modified` datetime(6) DEFAULT NULL,
  `modified_by` varchar(140) DEFAULT NULL,
  `owner` varchar(140) DEFAULT NULL,
  `docstatus` int(1) NOT NULL DEFAULT 0,
  `idx` int(8) NOT NULL DEFAULT 0,
  `asset` varchar(140) DEFAULT NULL,
  `version_hash` varchar(64) DEFAULT NULL,
  `source_hash` varchar(64) DEFAULT NULL,
  `width` int(11) NOT NULL DEFAULT 0,
  `height` int(11) NOT NULL DEFAULT 0,
  `dpi` int(11) NOT NULL DEFAULT 0,
  `colorspace` varchar(32) DEFAULT NULL,
  `policy_snapshot` longtext DEFAULT NULL,
  `crop_intent_snapshot` longtext DEFAULT NULL,
  `engine_version` varchar(64) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `is_active` int(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`name`),
  KEY `ix_modified` (`modified`),
  KEY `ix_asset` (`asset`),
  UNIQUE KEY `uk_version_hash` (`version_hash`)
) engine=InnoDB row_format=DYNAMIC character set=utf8mb4 collate=utf8mb4_unicode_ci;

alter table `tabMedia Version` add key `ix_asset_active` (`asset`,`is_active`);
