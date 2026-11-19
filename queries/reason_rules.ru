# make reason: OWL 2 RL rules as SPARQL updates (scripts/reason.py runs each block once per data graph, %GRAPH%).
# Inferred triples go to <urn:locx:graph:inferred>; asserted facts are never changed. TBox: the locx ontology graph,
# UniProt's core ontology (domains, ranges and subclasses of the up: terms) and the official GO and ECO releases. Rule names are those of the OWL 2 RL profile (W3C OWL 2 Profiles, section 4.3).
# Blocks are separated by lines starting with "#--"; scripts/reason.py runs them in this order.

PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX locx: <http://example.org/locx/>

#-- prp-spo1: a sub-property implies its super-property (e.g. locx:evidenceSentence -> oa:hasTarget)
INSERT { GRAPH <urn:locx:graph:inferred> { ?s ?super ?o } }
WHERE {
  VALUES ?tbox { <urn:locx:graph:ontology> <urn:locx:graph:uniprot-core> }
  GRAPH ?tbox { ?p rdfs:subPropertyOf ?super . FILTER isIRI(?super) }
  GRAPH <%GRAPH%> { ?s ?p ?o }
}

#-- prp-dom: the subject of a property is in its domain (named classes only; union domains are not materialized)
INSERT { GRAPH <urn:locx:graph:inferred> { ?s a ?class } }
WHERE {
  VALUES ?tbox { <urn:locx:graph:ontology> <urn:locx:graph:uniprot-core> }
  GRAPH ?tbox { ?p rdfs:domain ?class . FILTER isIRI(?class) }
  GRAPH <%GRAPH%> { ?s ?p ?o . FILTER NOT EXISTS { ?s a ?class } }
}

#-- prp-rng: the object of an object property is in its range (named classes only)
INSERT { GRAPH <urn:locx:graph:inferred> { ?o a ?class } }
WHERE {
  VALUES ?tbox { <urn:locx:graph:ontology> <urn:locx:graph:uniprot-core> }
  GRAPH ?tbox { ?p a owl:ObjectProperty ; rdfs:range ?class . FILTER isIRI(?class) }
  GRAPH <%GRAPH%> { ?s ?p ?o . FILTER (isIRI(?o) && NOT EXISTS { ?o a ?class }) }
}

#-- cax-sco (locx ontology): every superclass of a type, from the locx ontology and UniProt core (scripts/reason.py
#   also runs this block once with %GRAPH% = the inferred graph, for the types inferred from domains and ranges)
INSERT { GRAPH <urn:locx:graph:inferred> { ?x a ?super } }
WHERE {
  GRAPH <%GRAPH%> { ?x a ?c }
  VALUES ?tbox { <urn:locx:graph:ontology> <urn:locx:graph:uniprot-core> }
  GRAPH ?tbox { ?c rdfs:subClassOf+ ?super . FILTER isIRI(?super) }
}

#-- cax-sco (GO): every GO ancestor class of a location individual (is_a; part_of is an existential restriction,
#   which OWL 2 RL does not turn into a type)
INSERT { GRAPH <urn:locx:graph:inferred> { ?x a ?super } }
WHERE {
  GRAPH <%GRAPH%> { ?x a ?c . FILTER STRSTARTS(STR(?c), "http://purl.obolibrary.org/obo/GO_") }
  GRAPH <urn:locx:graph:go> { ?c rdfs:subClassOf+ ?super . FILTER isIRI(?super) }
}

#-- cax-sco (ECO): every ECO ancestor class of an evidence individual (e.g. experimental evidence)
INSERT { GRAPH <urn:locx:graph:inferred> { ?x a ?super } }
WHERE {
  GRAPH <%GRAPH%> { ?x a ?c . FILTER STRSTARTS(STR(?c), "http://purl.obolibrary.org/obo/ECO_") }
  GRAPH <urn:locx:graph:eco> { ?c rdfs:subClassOf+ ?super . FILTER isIRI(?super) }
}

#-- prp-ifp: two subjects with the same value of an inverse-functional property are the same (locx:orcid: the same
#   ORCID means the same person); eq-sym holds because both directions are written
INSERT { GRAPH <urn:locx:graph:inferred> { ?a owl:sameAs ?b } }
WHERE {
  GRAPH <urn:locx:graph:ontology> { ?p a owl:InverseFunctionalProperty }
  GRAPH <%GRAPH%> { ?a ?p ?v . ?b ?p ?v . FILTER (?a != ?b) }
}
