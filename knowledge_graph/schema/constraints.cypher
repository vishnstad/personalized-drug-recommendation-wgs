// Uniqueness constraints (also create backing indexes) for the pharmacogenomic KG.
// Run once against a fresh database before loading data.

CREATE CONSTRAINT gene_symbol IF NOT EXISTS FOR (g:Gene) REQUIRE g.symbol IS UNIQUE;
CREATE CONSTRAINT diplotype_id IF NOT EXISTS FOR (d:Diplotype) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT phenotype_id IF NOT EXISTS FOR (p:Phenotype) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT drug_rxnorm IF NOT EXISTS FOR (d:Drug) REQUIRE d.rxnorm_id IS UNIQUE;
CREATE CONSTRAINT guideline_id IF NOT EXISTS FOR (g:Guideline) REQUIRE g.id IS UNIQUE;
CREATE CONSTRAINT recommendation_id IF NOT EXISTS FOR (r:Recommendation) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT publication_pmid IF NOT EXISTS FOR (p:Publication) REQUIRE p.pmid IS UNIQUE;
CREATE CONSTRAINT adr_id IF NOT EXISTS FOR (a:ADR) REQUIRE a.id IS UNIQUE;

CREATE INDEX gene_hgnc IF NOT EXISTS FOR (g:Gene) ON (g.hgnc_id);
CREATE INDEX drug_name IF NOT EXISTS FOR (d:Drug) ON (d.name);
CREATE INDEX phenotype_gene IF NOT EXISTS FOR (p:Phenotype) ON (p.gene);
