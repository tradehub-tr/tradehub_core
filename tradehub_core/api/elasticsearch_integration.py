import frappe
import json
import logging

try:
	from elasticsearch import Elasticsearch
	HAS_ES = True
except ImportError:
	HAS_ES = False

logger = logging.getLogger("tradehub.elasticsearch")

def get_es_client():
	if not HAS_ES:
		return None
		
	# In production, these should come from site_config.json or frappe.conf
	es_host = frappe.conf.get("elasticsearch_host") or "http://elasticsearch:9200"
	
	try:
		es = Elasticsearch([es_host], max_retries=2, timeout=5)
		if es.ping():
			return es
	except Exception as e:
		logger.error(f"Elasticsearch connection failed: {e}")
	return None

def sync_document_to_es(doc, method=None):
	"""Hook: Called on on_update of Listing, Category, etc."""
	es = get_es_client()
	if not es:
		return
		
	index_name = f"istoc_{doc.doctype.lower().replace(' ', '_')}"
	
	doc_data = {
		"id": doc.name,
		"title": getattr(doc, "title", getattr(doc, "name")),
		"modified": str(doc.modified),
	}
	
	# Add specific fields based on doctype
	if doc.doctype == "Listing":
		doc_data["description"] = doc.get("description", "")
		doc_data["category"] = doc.get("category", "")
		doc_data["brand"] = doc.get("brand", "")
		doc_data["seller"] = doc.get("seller", "")
		doc_data["status"] = doc.get("status", "")
		
	try:
		es.index(index=index_name, id=doc.name, document=doc_data)
	except Exception as e:
		logger.error(f"Failed to sync {doc.name} to ES: {e}")

def remove_document_from_es(doc, method=None):
	"""Hook: Called on on_trash"""
	es = get_es_client()
	if not es:
		return
		
	index_name = f"istoc_{doc.doctype.lower().replace(' ', '_')}"
	
	try:
		es.delete(index=index_name, id=doc.name, ignore=[404])
	except Exception as e:
		logger.error(f"Failed to delete {doc.name} from ES: {e}")
