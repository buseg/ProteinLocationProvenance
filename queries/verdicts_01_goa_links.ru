# M8 step 1: link every assertion (protein P, GO term T) to the GOA rows of P whose term U is
#   locx:goaSame     U = T
#   locx:goaNarrower U lies below T  (U H+ T: the curated term is more specific than the paper's)
#   locx:goaBroader  U lies above T  (T H+ U: the curated term is broader than the paper's)
# with H = (rdfs:subClassOf | part_of) in the GO CC graph. ND rows ("no biological data") are skipped.

PREFIX locx: <http://example.org/locx/>
PREFIX obo:  <http://purl.obolibrary.org/obo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:goaSame ?g } }
WHERE {
  GRAPH <urn:locx:graph:assertions> { ?a locx:protein ?p ; locx:location ?t . }
  GRAPH <urn:locx:graph:goa-human>  { ?g locx:protein ?p ; locx:location ?t ; locx:evidenceCode ?ev . }
  FILTER (?ev != "ND")
} ;

INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:goaNarrower ?g } }
WHERE {
  GRAPH <urn:locx:graph:assertions> { ?a locx:protein ?p ; locx:location ?t . }
  GRAPH <urn:locx:graph:goa-human>  { ?g locx:protein ?p ; locx:location ?u ; locx:evidenceCode ?ev . }
  FILTER (?ev != "ND" && ?u != ?t)
  GRAPH <urn:locx:graph:go-cc>      { ?u (rdfs:subClassOf|obo:BFO_0000050)+ ?t . }
} ;

INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:goaBroader ?g } }
WHERE {
  GRAPH <urn:locx:graph:assertions> { ?a locx:protein ?p ; locx:location ?t . }
  GRAPH <urn:locx:graph:goa-human>  { ?g locx:protein ?p ; locx:location ?u ; locx:evidenceCode ?ev . }
  FILTER (?ev != "ND" && ?u != ?t)
  GRAPH <urn:locx:graph:go-cc>      { ?t (rdfs:subClassOf|obo:BFO_0000050)+ ?u . }
}
