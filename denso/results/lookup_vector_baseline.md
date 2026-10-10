# Lookup-tier evaluation (vector_baseline)

Correct (all part numbers + a right page, or a decline when not listed): **1/10**

| Q | OK | facts | page | s | route | answer |
|---|---|---|---|---|---|---|
| L1 | ❌ | 0.0 | False | 19.9 | Retrieved 1 source document(s) (lookup, naive, level 1) | The Spark Plug Catalogue 2025 (the only document provided) does not contain any entry for a 2015 Toyota Corolla with the vehicle code **NRE180** or a 1.3 L engi |
| L2 | ❌ | 0.0 | False | 8.6 | Retrieved 1 source document(s) (lookup, naive, level 1) | Trong tài liệu cung cấp không có thông tin về bugi DENSO cho Toyota Corolla 1.5 NZE161G năm 2014. |
| L3 | ❌ | 0.0 | False | 11.5 | Retrieved 1 source document(s) (lookup, naive, level 1) | I don’t have enough information to answer that question. The provided context does not contain any data for a Toyota Corolla 1.8 Hybrid ZWE186 or its DENSO spar |
| L4 | ❌ | 1.0 | False | 11.5 | Retrieved 1 source document(s) (lookup, naive, level 1) | The DENSO spark plug specified for a Honda City 1.5 i‑VTEC (model year 2005 and later) is **SKJ20DR‑M13** [1].    (Other DENSO plugs listed for this application |
| L5 | ❌ | 0.0 | False | 29.0 |  | HTTP 503: {"detail":"the answering LLM returned only its reasoning, no answer - please ask again"} |
| L6 | ✅ | 1.0 | True | 6.0 | Retrieved 1 source document(s) (lookup, naive, level 1) | For a 2019 Honda Civic sedan (model code FC1), the DENSO wiper blades listed in the Conventional Blade Series table are:  - **Driver side**     - DCP‑026R/L     |
| L7 | ❌ | 0.0 | False | 4.2 | Retrieved 2 source document(s) (lookup, naive, level 1) | Trong tài liệu được cung cấp không có thông tin về gạt mưa DENSO dành cho Ford Ranger năm 2018. Do đó, tôi không thể xác định mẫu gạt mưa DENSO phù hợp với xe n |
| L8 | ❌ | 0.0 | False | 7.2 | Retrieved 1 source document(s) (lookup, naive, level 1) | For a 2014 Mazda CX‑5, the DENSO wiper blade that fits is the **DRB‑014** (Rear Blade Series) [1]. |
| L9 | ❌ | 0.0 | False | 13.7 | Retrieved 2 source document(s) (lookup, naive, level 1) | The provided DENSO wiper blade lookup tables do not contain any entry for a 2008 Honda CR‑V (model code RE3). Consequently, the specific DENSO wiper blade part  |
| L10 | ❌ | None | None | 10.8 | Retrieved 1 source document(s) (lookup, naive, level 1) | I don’t have enough information to determine which DENSO spark plug fits a 2022 VinFast Fadil based on the provided Spark Plug Catalogue 2025.  The catalogue do |
