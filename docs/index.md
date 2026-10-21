# Documentation index

This folder describes a preprocessed dataset from MIMIC-IV 3.1. The dataset supports the prediction of acute kidney injury (AKI) in intensive care.

All documents are drafts. The clinical team must review them. The open items are in `preprocessing_notes.md`.

## Rule for these documents

Each fact has one home. A document links to the home of a fact. It does not repeat the fact.

## Which document answers which question

| Question | Document |
| --- | --- |
| How do I get the data, install the environment and run the pipeline? | [setup.md](setup.md) |
| What does the dataset contain? What are the rules for the stays, the label, the features and the splits? | [cohort_definition.md](cohort_definition.md) |
| What does each column mean? | [feature_dictionary.md](feature_dictionary.md) |
| Which MIMIC-IV item numbers does the pipeline use? | [itemids.md](itemids.md) |
| In which order do the scripts run? How do I run them? What do I run again after a change? | [pipeline.md](pipeline.md) |
| How did the pipeline make the dataset? Why? How many stays remain? What are the limits and the open items? | [preprocessing_notes.md](preprocessing_notes.md) |

## Reading order

1. `cohort_definition.md`
2. `preprocessing_notes.md`
3. `feature_dictionary.md`
4. `itemids.md`
5. `pipeline.md`
6. `setup.md` (before you run the pipeline)

## Languages

Each document has a Korean version. The name of the Korean file ends with `_kr`. The Korean index is [index_kr.md](index_kr.md).

The Korean version has the same content as the English version. The English version is the reference.
