# Verdicts step 1: one locx:Verdict per assertion (IRI locx:verdict/<assertion key>), linked to the GOA rows of the
# same protein whose GO term U relates to the assertion's term T:
#   locx:goaSame     U = T
#   locx:goaNarrower U lies below T  (the curated term is more specific than the papers')
#   locx:goaBroader  U lies above T  (the curated term is broader than the papers')
# "Below" walks the official GO release (graph go): rdfs:subClassOf, or part_of, which GO states as an OWL restriction
# (rdfs:subClassOf [owl:onProperty part_of ; owl:someValuesFrom X]). GOA rows whose ECO evidence type carries ECO's own
# "has GO evidence code" = ND (no biological data) are skipped. %ACTIVITY% = the verdict activity IRI.

PREFIX rdf:      <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX locx: <http://example.org/locx/>
PREFIX obo:  <http://purl.obolibrary.org/obo/>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

INSERT { GRAPH <urn:locx:graph:verdicts> { ?v a locx:Verdict ; locx:about ?a ; prov:wasGeneratedBy <%ACTIVITY%> } }
WHERE {
  GRAPH <urn:locx:graph:assertions> { ?a a locx:Assertion . }
  BIND (IRI(REPLACE(STR(?a), "/assertion/", "/verdict/")) AS ?v)
} ;

INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:goaSame ?g } }
WHERE {
  GRAPH <urn:locx:graph:verdicts>   { ?v locx:about ?a . }
  GRAPH <urn:locx:graph:assertions> { ?a locx:protein ?p ; locx:location/rdf:type ?t . }
  GRAPH <urn:locx:graph:goa-human>  { ?g locx:protein ?p ; locx:location/rdf:type ?t ; locx:evidence/rdf:type ?ev . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:eco> { ?ev obo:ECO_9000002 "ND" } }
} ;

INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:goaNarrower ?g } }
WHERE {
  GRAPH <urn:locx:graph:verdicts>   { ?v locx:about ?a . }
  GRAPH <urn:locx:graph:assertions> { ?a locx:protein ?p ; locx:location/rdf:type ?t . }
  GRAPH <urn:locx:graph:goa-human>  { ?g locx:protein ?p ; locx:location/rdf:type ?u ; locx:evidence/rdf:type ?ev . }
  FILTER (?u != ?t)
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:eco> { ?ev obo:ECO_9000002 "ND" } }
  GRAPH <urn:locx:graph:go>         { ?u (rdfs:subClassOf|rdfs:subClassOf/owl:someValuesFrom)+ ?t . }
} ;

INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:goaBroader ?g } }
WHERE {
  GRAPH <urn:locx:graph:verdicts>   { ?v locx:about ?a . }
  GRAPH <urn:locx:graph:assertions> { ?a locx:protein ?p ; locx:location/rdf:type ?t . }
  GRAPH <urn:locx:graph:goa-human>  { ?g locx:protein ?p ; locx:location/rdf:type ?u ; locx:evidence/rdf:type ?ev . }
  FILTER (?u != ?t)
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:eco> { ?ev obo:ECO_9000002 "ND" } }
  GRAPH <urn:locx:graph:go>         { ?t (rdfs:subClassOf|rdfs:subClassOf/owl:someValuesFrom)+ ?u . }
}
