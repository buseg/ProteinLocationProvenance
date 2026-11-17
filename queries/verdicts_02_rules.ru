# M8 step 2: one verdict per assertion (SPEC M8), applied in order; each rule only touches
# assertions that have no verdict yet. Needs step 1 (goaSame / goaNarrower / goaBroader links).
# %RUN_GRAPH% = the extraction run's named graph. The GOA rows behind a verdict get locx:goaMatch.
#
#                 present                                   absent
# Error           no valid mention (sanity check)           same
# Uninformative   T is too generic                          same
# Conflicting     NOT on T or broader                       positive on T or narrower
# Consistent      positive on T or narrower                 NOT on T or broader
# Refinement      positive only on broader (not generic)    -
# Novel           anything else                             anything else

PREFIX locx: <http://example.org/locx/>

# Error
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict locx:Error } }
WHERE {
  GRAPH <urn:locx:graph:assertions> { ?a a locx:Assertion . }
  FILTER NOT EXISTS { GRAPH <%RUN_GRAPH%> { ?m locx:asserts ?a ; locx:valid true . } }
} ;

# Uninformative
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict locx:Uninformative } }
WHERE {
  GRAPH <urn:locx:graph:assertions> { ?a locx:location ?t . }
  GRAPH <urn:locx:graph:go-cc> { ?t locx:tooGeneric true . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict ?any } }
} ;

# Conflicting
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict locx:Conflicting ; locx:goaMatch ?g } }
WHERE {
  {
    GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Present . }
    GRAPH <urn:locx:graph:verdicts>   { ?a locx:goaSame|locx:goaBroader ?g . }
    GRAPH <urn:locx:graph:goa-human>  { ?g locx:negated true . }
  } UNION {
    GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Absent . }
    GRAPH <urn:locx:graph:verdicts>   { ?a locx:goaSame|locx:goaNarrower ?g . }
    GRAPH <urn:locx:graph:goa-human>  { ?g locx:negated false . }
  }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict ?any } }
} ;

# Consistent
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict locx:Consistent ; locx:goaMatch ?g } }
WHERE {
  {
    GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Present . }
    GRAPH <urn:locx:graph:verdicts>   { ?a locx:goaSame|locx:goaNarrower ?g . }
    GRAPH <urn:locx:graph:goa-human>  { ?g locx:negated false . }
  } UNION {
    GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Absent . }
    GRAPH <urn:locx:graph:verdicts>   { ?a locx:goaSame|locx:goaBroader ?g . }
    GRAPH <urn:locx:graph:goa-human>  { ?g locx:negated true . }
  }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict ?any } }
} ;

# Refinement (present only): positive GOA only on broader, non-generic terms
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict locx:Refinement ; locx:goaMatch ?g } }
WHERE {
  GRAPH <urn:locx:graph:assertions> { ?a locx:polarity locx:Present . }
  GRAPH <urn:locx:graph:verdicts>   { ?a locx:goaBroader ?g . }
  GRAPH <urn:locx:graph:goa-human>  { ?g locx:negated false ; locx:location ?u . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:go-cc> { ?u locx:tooGeneric true . } }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict ?any } }
} ;

# Novel
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict locx:Novel } }
WHERE {
  GRAPH <urn:locx:graph:assertions> { ?a a locx:Assertion . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?a locx:verdict ?any } }
} ;

# Context: a supporting valid mention states a condition (cannot be resolved automatically yet)
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:contextDependent true } }
WHERE {
  GRAPH <%RUN_GRAPH%> { ?m locx:asserts ?a ; locx:valid true ; locx:condition ?c . }
} ;

# Weak: every GOA row behind the verdict is colocalizes_with
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:weakGoaMatch true } }
WHERE {
  GRAPH <urn:locx:graph:verdicts> { ?a locx:goaMatch ?g0 . }
  FILTER NOT EXISTS {
    GRAPH <urn:locx:graph:verdicts>  { ?a locx:goaMatch ?g . }
    GRAPH <urn:locx:graph:goa-human> { ?g locx:qualifier ?q . }
    FILTER (?q != "colocalizes_with")
  }
} ;

# Evidence: does any GOA row behind the verdict have experimental evidence?
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:goaExperimental true } }
WHERE {
  GRAPH <urn:locx:graph:verdicts>  { ?a locx:goaMatch ?g . }
  GRAPH <urn:locx:graph:goa-human> { ?g locx:evidenceCode ?ev . }
  FILTER (?ev IN ("EXP", "IDA", "IPI", "IMP", "IGI", "IEP", "HTP", "HDA", "HMP", "HGI", "HEP"))
} ;

INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:goaExperimental false } }
WHERE {
  GRAPH <urn:locx:graph:verdicts> { ?a locx:goaMatch ?g . }
  FILTER NOT EXISTS { GRAPH <urn:locx:graph:verdicts> { ?a locx:goaExperimental true } }
}
 ;

# Evidence group: the strongest GO evidence group among the GOA rows behind the verdict
#   (experimental > high_throughput > author_statement > curator > computational > electronic; table in locx/evidence.py)
INSERT { GRAPH <urn:locx:graph:verdicts> { ?a locx:goaEvidence ?evGroup } }
WHERE {
  { SELECT ?a (MIN(?evRank) AS ?best) WHERE {
      GRAPH <urn:locx:graph:verdicts>  { ?a locx:goaMatch ?g . }
      GRAPH <urn:locx:graph:goa-human> { ?g locx:evidenceCode ?ev . }
      VALUES (?ev ?evRank) { %EVIDENCE_CODES% }
    } GROUP BY ?a }
  VALUES (?evGroup ?best) { %EVIDENCE_GROUPS% }
}
