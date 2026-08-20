"""Medya motoru arayüz sözleşmeleri — T-031, DONDURULMUŞ.

Beş çekirdek arayüz ve ortak hata hiyerarşisi. Hepsi `typing.Protocol`:
nominal değil yapısal tipleme, yani bir uygulamanın bu paketten türemesi
gerekmez — imzayı karşılaması yeter. Bu, `tradehub_core/media/` altındaki
çalışan modüllerin sözleşmeye uydurulmasını, onları değiştirmeden ince bir
sarmalayıcıyla mümkün kılar.

İmza değişikliği `tradehub_core/media/pipeline/contracts/signatures.golden.json` ile korunuyor;
`tests/test_contracts.py::SignatureGoldenTest` uyuşmazlıkta kırılır.
"""

from tradehub_core.media.pipeline.contracts.delivery import DeliveryManifest, RenderManifest, SourceSet, Variant
from tradehub_core.media.pipeline.contracts.errors import (
	DecodeError,
	DeliveryError,
	EncodeError,
	ImageError,
	MediaEngineError,
	NoProfileAvailable,
	ObjectNotFound,
	OversizedImage,
	PolicyError,
	PolicyNotFound,
	PolicyViolation,
	ProbeUnavailable,
	StorageConflict,
	StorageError,
	TranscodeFailed,
	UnsupportedFormat,
	VideoError,
)
from tradehub_core.media.pipeline.contracts.image import (
	EncodedImage,
	ImageEngine,
	ImageProbe,
	MasterSpec,
	QualityReport,
	RenditionSpec,
)
from tradehub_core.media.pipeline.contracts.policy import Decision, PolicyEngine, SlotPolicy, Violation
from tradehub_core.media.pipeline.contracts.storage import ObjectKey, ObjectRef, ObjectStat, PutResult, StorageAdapter
from tradehub_core.media.pipeline.contracts.video import (
	PosterSpec,
	PreviewClipSpec,
	VideoArtifact,
	VideoEngine,
	VideoProbe,
	VideoRenditionSpec,
	VideoSource,
)

#: Beş çekirdek arayüz — sözleşme testleri ve imza altın dosyası bu sırayı kullanır.
CORE_PROTOCOLS = (
	StorageAdapter,
	ImageEngine,
	VideoEngine,
	PolicyEngine,
	DeliveryManifest,
)

__all__ = [
	"CORE_PROTOCOLS",
	# storage
	"StorageAdapter",
	"ObjectKey",
	"ObjectRef",
	"ObjectStat",
	"PutResult",
	# image
	"ImageEngine",
	"ImageProbe",
	"MasterSpec",
	"RenditionSpec",
	"EncodedImage",
	"QualityReport",
	# video
	"VideoEngine",
	"VideoSource",
	"VideoProbe",
	"VideoRenditionSpec",
	"PosterSpec",
	"PreviewClipSpec",
	"VideoArtifact",
	# policy
	"PolicyEngine",
	"SlotPolicy",
	"Decision",
	"Violation",
	# delivery
	"DeliveryManifest",
	"RenderManifest",
	"Variant",
	"SourceSet",
	# errors
	"MediaEngineError",
	"PolicyError",
	"PolicyNotFound",
	"PolicyViolation",
	"StorageError",
	"ObjectNotFound",
	"StorageConflict",
	"ImageError",
	"DecodeError",
	"EncodeError",
	"UnsupportedFormat",
	"OversizedImage",
	"VideoError",
	"ProbeUnavailable",
	"TranscodeFailed",
	"DeliveryError",
	"NoProfileAvailable",
]
