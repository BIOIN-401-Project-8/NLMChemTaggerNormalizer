import re

from bioc import biocxml

class DocumentProcessor:
	# TODO Add timing logs

	def __init__(self, type2normalizer, abbr):
		self.type2normalizer = type2normalizer
		self.abbr = abbr
	
	def process_file(self, input_filename, output_filename):
		with open(input_filename, "r") as fp:
			collection = biocxml.load(fp)
		for document in collection.documents:
			self.process_document(document)
		with open(output_filename, "w") as fp:
			biocxml.dump(collection, fp)
		
	def process_document(self, document):
		text2expanded, expanded2lookup = self.extract_mentions(document)
		#print("expanded2lookup.keys() = " + str(expanded2lookup.keys()))
		#print("expanded2lookup = " + str(expanded2lookup))
		# Performs post-processing
		expanded2final = self.post_process(document.id, expanded2lookup)
		#print("expanded2final.keys() = " + str(expanded2final.keys()))
		#print("expanded2final = " + str(expanded2final))
		self.apply_lookup(document, text2expanded, expanded2final)

	def extract_mentions(self, document):
		# First pass creates mappings from mention text to expanded text and from expanded text to entities
		text2expanded = dict()
		expanded2lookup = dict()
		for passage in document.passages:
			for annotation in passage.annotations:
				if not "type" in annotation.infons:
					continue
				entity_type = annotation.infons["type"]
				if not entity_type in self.type2normalizer:
					continue
				if annotation.text is None:
					continue
				if annotation.text in text2expanded:
					continue
				text_expanded = self.abbr.expand(document.id, annotation.text)
				text2expanded[annotation.text] = text_expanded
				if text_expanded in expanded2lookup:
					continue
				print("MENTION\t" + document.id + "\t" + annotation.id + "\t" + entity_type + "\t" + annotation.text + "\t" + text_expanded)
				normalizer = self.type2normalizer[entity_type]
				target_entities = normalizer.normalize_mention(text_expanded)
				expanded2lookup[text_expanded] = ([0], entity_type, target_entities)
		return text2expanded, expanded2lookup
	
	def apply_lookup(self, document, text2expanded, expanded2final):
		for passage in document.passages:
			annotation_list = passage.annotations.copy()
			passage.annotations.clear()
			for annotation in annotation_list:
				if not "type" in annotation.infons:
					continue
				type = annotation.infons["type"]
				if not type in self.type2normalizer:
					continue
				if annotation.text is None:
					continue
				text_expanded = text2expanded[annotation.text]
				lookup_tuple = expanded2final[text_expanded]
				processing_path = lookup_tuple[0]
				# TODO Evaluate allowing post-processing to change type
				entity_type = lookup_tuple[1] 
				normalizer = self.type2normalizer[entity_type]
				target_entities = list(lookup_tuple[2])
				target_entities.sort()
				names = list()
				for target_entity in target_entities:
					if target_entity in normalizer.id2name:
						names.append(normalizer.id2name[target_entity])
					else:
						names.append("UNKNOWN")
				print("NORM\t" + document.id + "\t" + annotation.text + "\t" + text_expanded + "\t" + str(processing_path) + "\t" + str(len(target_entities)) + "\t" + str(target_entities) + "\t" + str(names))
				if len(target_entities) > 0:
					identifier = ",".join(target_entities)
					if len(identifier) > 0:
						annotation.infons["identifier"] = identifier
					elif "identifier" in annotation.infons:
						del annotation.infons["identifier"]
					passage.annotations.append(annotation)
							
	# TODO Refactor postprocessing to be a separate class
	def post_process(self, document_id, expanded2lookup):
		# Post-processing
		# First pass does filtering and looks for unambiguous mentions
		unambiguous_entities = set()
		expanded2final = dict()
		expanded2lookup2 = dict()
		for text_expanded, lookup_tuple in expanded2lookup.items():
			processing_path = lookup_tuple[0]
			entity_type = lookup_tuple[1]
			normalizer = self.type2normalizer[entity_type]
			target_entities = lookup_tuple[2]
			if not re.search("[A-Za-z]", text_expanded):
				# No text => filter
				processing_path.append(1)
				expanded2final[text_expanded] = (processing_path, entity_type, {})
				print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\tFILTER")
			elif len(target_entities) == 0: 
				# No matches => Unknown
				processing_path.append(2)
				id = {normalizer.unknown_id}
				expanded2final[text_expanded] = (processing_path, entity_type, {normalizer.unknown_id})
				print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\tUNKNOWN")
			elif len(target_entities) == 1: 
				# Unambiguous
				unambiguous_entities.update(target_entities)
				processing_path.append(3)
				expanded2lookup2[text_expanded] = (processing_path, entity_type, target_entities)
				print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\t" + str(target_entities) + "\tUNAMBIGUOUS")
			else:
				# Ambiguous
				processing_path.append(4)
				expanded2lookup2[text_expanded] = (processing_path, entity_type, target_entities)
				print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\t" + str(target_entities) + "\tAMBIGUOUS")
		# Resolve ambiguous
		expanded2lookup = expanded2lookup2
		expanded2lookup2 = dict()
		for text_expanded, lookup_tuple in expanded2lookup.items():
			processing_path = lookup_tuple[0]
			entity_type = lookup_tuple[1]
			target_entities = lookup_tuple[2]
			if len(target_entities) == 1:
				# Not ambiguous
				processing_path.append(5)
				expanded2lookup2[text_expanded] = (processing_path, entity_type, target_entities)
				print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\t" + str(target_entities) + "\tUNAMBIGUOUS")
			else:
				resolved = target_entities.intersection(unambiguous_entities)
				if len(resolved) == 0:
					# Fall back to the target entities
					processing_path.append(6)
					expanded2lookup2[text_expanded] = (processing_path, entity_type, target_entities)
					print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\t" + str(resolved) + "\tFALLBACK")
				else:
					processing_path.append(7)
					expanded2lookup2[text_expanded] = (processing_path, entity_type, resolved)
					print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\t" + str(resolved) + "\tRESOLVED")
		# Filter non-allowed, map to unknown if still ambiguous
		expanded2lookup = expanded2lookup2
		for text_expanded, lookup_tuple in expanded2lookup.items():
			processing_path = lookup_tuple[0]
			entity_type = lookup_tuple[1]
			target_entities = lookup_tuple[2]
			normalizer = self.type2normalizer[entity_type]
			resolved = target_entities.intersection(normalizer.allowed_ids)
			if resolved != target_entities:
				# Some non-allowed ids removed
				processing_path.append(8)
				print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\t" + str(resolved) + "\tREMNALLOW")
			if len(resolved) > 1:
				# Still ambiguous
				resolved = {normalizer.unknown_id}
				processing_path.append(9)
				print("POST\t" + document_id + "\t" + text_expanded + "\t" + str(processing_path) + "\t" + str(resolved) + "\tSTILLAMBIG")
			expanded2final[text_expanded] = (processing_path, entity_type, resolved)
		return expanded2final
