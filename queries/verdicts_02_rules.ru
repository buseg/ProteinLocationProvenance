# Verdicts step 2: the outcome of each verdict (needs step 1), applied in order; each rule only touches verdicts
# without an outcome yet. GOA rows and assertions are both localization statements with locx:polarity (GOA NOT =
# locx:Absent). Too-generic GO terms are stated in the locx ontology (graph ontology). The GOA rows the outcome rests
# on get locx:goaMatch.
#
#                 present assertion                          absent assertion
# Error           no valid claim (sanity check)              same
# Uninformative   T is too generic                           same
# Conflicting     absent GOA row on T or broader             present GOA row on T or narrower
# Consistent      present GOA row on T or narrower           absent GOA row on T or broader
# Refinement      present GOA rows only on broader terms     -
#                 that are not too generic
# Novel           anything else                              anything else

PREFIX rdf:      <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX locx: <http://example.org/locx/>
PREFIX obo:  <http://purl.obolibrary.org/obo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX prov: <http://www.w3.org/ns/prov#>

# Error
INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome locx:Error } }
WHERE {
  GRAPH <urn:locx:graph:verdicts> { ?v locx:about ?a . }
  FILTER NOT EXISTS { GRAPH <%RUN_GRAPH%> { ?c locx:asserts ?a ; locx:valid true . } }
} ;

# Uninformative
INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome locx:Uninformative } }
WHERE {
  GRAPH <urn:locx:graph:verdicts>   { ?v locx:about ?a . }
  GRAPH <urn:locx:graph:assertions> { ?a locx:location/rdf:type ?t . }
  GRAPH <urn:locx:graph:ontology>   { ?t locx:tooGeneric true . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome ?any } }
} ;

# Conflicting
INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome locx:Conflicting ; locx:goaMatch ?g } }
WHERE {
  GRAPH <urn:locx:graph:verdicts> { ?v locx:about ?a . }
  {
    GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Present . }
    GRAPH <urn:locx:graph:verdicts>   { ?v locx:goaSame|locx:goaBroader ?g . }
    GRAPH <urn:locx:graph:goa-human>  { ?g locx:polarity locx:Absent . }
  } UNION {
    GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Absent . }
    GRAPH <urn:locx:graph:verdicts>   { ?v locx:goaSame|locx:goaNarrower ?g . }
    GRAPH <urn:locx:graph:goa-human>  { ?g locx:polarity locx:Present . }
  }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome ?any } }
} ;

# Consistent
INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome locx:Consistent ; locx:goaMatch ?g } }
WHERE {
  GRAPH <urn:locx:graph:verdicts> { ?v locx:about ?a . }
  {
    GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Present . }
    GRAPH <urn:locx:graph:verdicts>   { ?v locx:goaSame|locx:goaNarrower ?g . }
    GRAPH <urn:locx:graph:goa-human>  { ?g locx:polarity locx:Present . }
  } UNION {
    GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Absent . }
    GRAPH <urn:locx:graph:verdicts>   { ?v locx:goaSame|locx:goaBroader ?g . }
    GRAPH <urn:locx:graph:goa-human>  { ?g locx:polarity locx:Absent . }
  }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome ?any } }
} ;

# Refinement (present only): present GOA rows only on broader terms that are not too generic
INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome locx:Refinement ; locx:goaMatch ?g } }
WHERE {
  GRAPH <urn:locx:graph:verdicts>   { ?v locx:about ?a ; locx:goaBroader ?g . }
  GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Present . }
  GRAPH <urn:locx:graph:goa-human>  { ?g locx:polarity locx:Present ; locx:location/rdf:type ?u . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:ontology> { ?u locx:tooGeneric true . } }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome ?any } }
} ;

# Novel
INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome locx:Novel } }
WHERE {
  GRAPH <urn:locx:graph:verdicts> { ?v locx:about ?a . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?v locx:outcome ?any } }
} ;

# Strongest evidence: the GO evidence category (locx ontology, section 9) of the strongest GOA row behind the outcome.
# A row's ECO term is in a category when it lies under one of the category's ECO roots (rdfs:subClassOf* in graph eco)
# and under none of its excluded roots; locx:evidenceRank orders the categories (1 = strongest).
INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:strongestEvidence ?category } }
WHERE {
  { SELECT ?v (MIN(?rank) AS ?best) WHERE {
      GRAPH <urn:locx:graph:verdicts>  { ?v locx:goaMatch ?g . }
      GRAPH <urn:locx:graph:goa-human> { ?g locx:evidence/rdf:type ?ev . }
      GRAPH <urn:locx:graph:ontology>  { ?c locx:ecoRoot ?root ; locx:evidenceRank ?rank . }
      GRAPH <urn:locx:graph:eco>       { ?ev rdfs:subClassOf* ?root . }
      FILTER NOT EXISTS {
        GRAPH <urn:locx:graph:ontology> { ?c locx:ecoExcludedRoot ?excluded . }
        GRAPH <urn:locx:graph:eco>      { ?ev rdfs:subClassOf* ?excluded . }
      }
    } GROUP BY ?v }
  GRAPH <urn:locx:graph:ontology> { ?category locx:evidenceRank ?best . }
} ;

# Curated from the same paper: a GOA row linked to the assertion cites one of the papers its claims come from
INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:curatedFromSamePaper true } }
WHERE {
  GRAPH <urn:locx:graph:verdicts>  { ?v locx:about ?a ; locx:goaSame|locx:goaNarrower|locx:goaBroader ?g . }
  GRAPH <urn:locx:graph:goa-human> { ?g dcterms:source ?paper . }
  GRAPH <%RUN_GRAPH%>              { ?c locx:asserts ?a ; prov:wasDerivedFrom ?paper . }
} ;

INSERT { GRAPH <urn:locx:graph:verdicts> { ?v locx:curatedFromSamePaper false } }
WHERE {
  GRAPH <urn:locx:graph:verdicts> { ?v a locx:Verdict . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?v locx:curatedFromSamePaper true } }
}
