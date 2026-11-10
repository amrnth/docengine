Thank you for olmOCR-bench. I use it a lot, and I found some tests that I think need a second look.

**Summary.** In dataset revision `54a96a6` there are 38 tests, all marked `checked: verified`, that a faithful transcription of the page cannot pass:

- **32 `order` / `present` tests** expect a string that is not what the page shows. Examples: the test has "sternum" where the page has "scrotum", "line 2 of the Schedule D" for "line 37a of Schedule D", "Barkschat R (2021)" for "Blankertz B (2001)".
- **6 `absent` tests** forbid a string that is also part of the body text of the same page.

Together they are worth 0.61 points of the overall score (28 of 884 in `multi_column`, 4 of 442 in `long_tiny_text`, 6 of 760 in `headers_footers`).

**How I found them**

1. For every `present` / `order` test on a page that has embedded text, I applied the test's own rule (same `normalize_text`, same `max_diffs`) to the text stored in the PDF. To allow for artefacts of the stored text, a match also counts with line-break hyphens joined, accents removed, case ignored, or all spaces removed. 1,100 tests could be checked; 120 had no match.
2. I kept a test only if the stored text has a different string in that place, and at least 3 of 4 unrelated model families (LightOnOCR-3, Infinity-Parser2, olmOCR-2, OvisOCR2) output that string and not the test's string. This removes the cases where the stored text itself is wrong (OCR layers, lost ligatures). 37 tests were left.
3. I looked at a crop of the page for each one and dropped 5 (one test was right, four were layout or convention questions). For one of the 32 that are left (`019a8841dddeb304774ba62a9f5d8dccb43d_page_1.pdf_order_87cd96c5`) my crop missed the sentence, so that row rests on the embedded text and the four models only.

None of the 14 runs I have (the four families above and cascades of them) passes any of the 32 tests.

This method cannot check scanned pages, math or tables, so I have nothing to say about those. I may also be wrong on some rows; please tell me if so.

### A. Expected string differs from the page (32 tests)

Only the part that differs is shown, with the differing words in bold. "Page shows" is the PDF's embedded text. Differences that are only an accent are not marked.

| Test id | Type (field) | Test expects | Page shows |
|---|---|---|---|
| `20_pg39_pg1_text_06` | present (`text`) | … Sandi Toksvig - her **Ql** training coming in handy … | … Sandi Toksvig - her **QI** training coming in handy … |
| `13_pg162_pg1_text_05` | present (`text`) | **The Luther** state offers the parish … | **Baden the** state offers the parish … |
| `20_pg32_pg1_text_05` | present (`text`) | … witch", an "evil-doer" and **"anti-American** zombie". | … witch", an "evil-doer" and **"an anti-American** zombie". |
| `11_pg146_pg1_text_00` | present (`text`) | PERTE. (1) **Το** part. Still in use. | PERTE. (1) **To** part. Still in use. |
| `0208fbb5d6b646f972f4702428ad2cede5c5_page_8.pdf_order_e8b33660` | order (`after`) | … 1988, 1989, and 1990 **(Mehring** 1991) induced a remarkably … | … 1988, 1989, and 1990 **(Meining** 1991) induced a remarkably … |
| `06df5e530c2ccb0310a3205586a37d4b9b7d_page_4.pdf_order_59dca065` | order (`before`) | … estructural y no está **directamente** ligado a crisis coyunturales. | … estructural y no está **únicamente** ligado a crisis coyunturales. |
| `0005784d0d255f6652180433936fa2998188_page_4.pdf_order_c5b84575` | order (`after`) | … engagement model might be **warranted.** | … engagement model might be **required.** |
| `0a7e813e2010ecd8239725c32c859fe00c92_page_2.pdf_order_45e2eb29` | order (`before`) | A ovi ljudi u **trajnhu** - oni su jedva … | A ovi ljudi u **triptihu** - oni su jedva … |
| `0a7e813e2010ecd8239725c32c859fe00c92_page_2.pdf_order_db6f3a51` | order (`before`) | Meni je **to** bilo užasno žao. | Meni **ih** je bilo užasno žao. |
| `0a7e813e2010ecd8239725c32c859fe00c92_page_2.pdf_order_3e896fa6` | order (`before`) | A onda se **jednom** dogodila iznimno komična situacija: **pokraj** prvog čina, za vrijeme dramske pauze, **najjednoput erno** čuli **hihotanje:** vatrogasac je zaspao gore … | A onda se **jedanput** dogodila iznimno komična situacija: **potkraj** prvog čina, za vrijeme dramske pauze, **najedanput smo** čuli **hrkanje:** vatrogasac je zaspao gore … |
| `0a7e813e2010ecd8239725c32c859fe00c92_page_2.pdf_order_3e896fa6` | order (`after`) | Rekao je da on **ne razumije** da on nikada ne bi mogao biti glumac jer mi moramo iz večeri u večer igrati jednu te istu predstavu, **kako** da **mu** znao da predstava tek … | Rekao je da on **glumca žali i** da on nikada ne bi mogao biti glumac jer mi moramo iz večeri u večer igrati jednu te istu predstavu, **kao** da **nije** znao da predstava tek … |
| `0a7e813e2010ecd8239725c32c859fe00c92_page_2.pdf_order_b06ed1c4` | order (`before`) | … jako začudilo da jedan **muški** redatelj nije imao sluha za **potrebbe** glumice. | … jako začudilo da jedan **mladi** redatelj nije imao sluha za **potrebe** glumice. |
| `07070be1377058b90fd5fce677361eda4e3f_page_9.pdf_order_47fe2ee7` | order (`before`) | … team of the INRIA **Rhône-Alpes, part** of the LJK; | … team of the INRIA **Rhone-Alpes and** of the LJK; |
| `07c14b471fd33c56b988cc7a58dae211d16f_page_13.pdf_order_87cde7ba` | order (`after`) | … a three bit index **(0,1,1)** that specifies a marking … | … a three bit index **(1,0,0)** that specifies a marking … |
| `019a8841dddeb304774ba62a9f5d8dccb43d_page_1.pdf_order_87cd96c5` | order (`after`) | … présence d'une dynamine 2 **anormale** pourrait être nécessaire à l'endocytose du récepteur du **G-CSF** (granulocyte colony-stimulating factor) qui … | … présence d'une dynamine 2 **normale** pourrait être nécessaire à l'endocytose du récepteur du **GCSF** (granulocyte colony-stimulating factor) qui … |
| `0621a0090414e4681e90a4e1ea543acca910_page_18.pdf_order_e0405e92` | order (`after`) | L'étude **comparative** des arbres stylistiques | L'étude **comparée** des arbres stylistiques |
| `0904c7071324813f138e96ed004bbc613748_page_6.pdf_order_22ca6197` | order (`before`) | … velocity profile (see Eq. **(28))** when | … velocity profile (see Eq. **(28)** when |
| `00f6c2eea6b51fb1bf637b5f8a850588d7e2_page_13.pdf_order_40575929` | order (`before`) | [46] **Barkschat R (2021)** The constant Q transform. | [46] **Blankertz B (2001)** The constant Q transform. |
| `00f6c2eea6b51fb1bf637b5f8a850588d7e2_page_13.pdf_order_bec1d2a5` | order (`before`) | [35] **Baranisak RK, Delo** EJ (2021) Frequency domain-based … | [35] **Bartusiak ER, Delp** EJ (2021) Frequency domain-based … |
| `00f6c2eea6b51fb1bf637b5f8a850588d7e2_page_13.pdf_order_33d8a975` | order (`before`) | [38] Huang **F, Yao** CM (2020) Audio replay … | [38] Huang **L, Pun** CM (2020) Audio replay … |
| `00f6c2eea6b51fb1bf637b5f8a850588d7e2_page_13.pdf_order_33d8a975` | order (`after`) | [59] **Hu** Y, **Wodey** S (2019) The real-world-weight … | [59] **Ho** Y, **Wookey** S (2019) The real-world-weight … |
| `00f6c2eea6b51fb1bf637b5f8a850588d7e2_page_13.pdf_order_6ef1a2f1` | order (`after`) | [60] Khalid H, Woo **SS, Lip Tang S,** SS **(2020,** October) Evaluation of an … | [60] Khalid H, **Kim M, Tariq S,** Woo SS **(2021b,** October) Evaluation of an … |
| `069577d83be73a2373200ada5599eb824c95_page_2.pdf_order_a9531409` | order (`before`) | **Burr with heady** eyes sparkled but his … | **rose. His beady** eyes sparkled but his … |
| `07f4d706dd1736e247163f0128702c65bdd8_page_1.pdf_order_e4818f1a` | order (`after`) | Exclusion criteria included the **following:** (1) the DES was implanted for left main coronary disease, (2) there were overlapping DESs implanted in the lesion, (3) the clinical follow-up period after DES implantation was <1 year, (4) follow-up OCT was performed >1 year after DES implantation, and (5) the OCT **images** had poor quality. | Exclusion criteria included the **following** (1) the DES was implanted for left main coronary disease, (2) there were overlapping DESs implanted in the lesion, (3) the clinical follow-up period after DES implantation was <1 year, (4) follow-up OCT was performed >1 year after DES implantation, and (5) the OCT **image** had poor quality. |
| `06ba2a90e81d76b586e6b884bf67133012a9_page_8.pdf_order_1ce1f177` | order (`before`) | (Medina et al., 2000). Consistently, the overall … | (Medina et al., **1993,** 2000). Consistently, the overall … |
| `06ba2a90e81d76b586e6b884bf67133012a9_page_8.pdf_order_ce82b35f` | order (`after`) | … influence on vaccine-induced antibody **responses.** | … influence on vaccine-induced antibody **response.** |
| `06ba2a90e81d76b586e6b884bf67133012a9_page_14.pdf_order_34c8ca58` | order (`after`) | **Karni** G, Yalcin **S, Coymak Y,** Yurdakök K. Clinical trial … | **Kanra** G, Yalcin **SS,Ceyhan M,** Yurdakok K. Clinical trial … |
| `09f801e3a2ec90ef456d34ad571a46f36fce_page_3.pdf_order_20f078ea` | order (`before`) | **Communication** du Conseil départemental du … | **Président** du Conseil départemental du … |
| `05aa71fa77e07bccb443ef4fd28dde3ecfd6_page_12.pdf_order_f2676f76` | order (`after`) | **Schickinger,** R. M., S. E. … | **Schowalter,** R. M., S. E. … |
| `07619750fcfe3caff8ec82642ac2449b490a_page_1.pdf_order_2b21c23d` | order (`before`) | **Rokotuksen** mahdollinen käyttöönotto vaatii huolellista … | **Rokotusten** mahdollinen käyttöönotto vaatii huolellista … |
| `01119fb525785eb7153ee600241ff1e01959_page_2.pdf_order_528457cb` | order (`after`) | … raised edges on the **sternum** and upper thighs. | … raised edges on the **scrotum** and upper thighs. |
| `0514f6672af23035c53e13fa9f5d7e17e4a4_page_18.pdf_order_b3170ed9` | order (`before`) | Iwata, H., **Yatogami,** M., van Randow, C., … | Iwata, H., **Yadvinder,** M., van Randow, C., … |
| `0514f6672af23035c53e13fa9f5d7e17e4a4_page_18.pdf_order_dfe28954` | order (`before`) | **Heinsch, F., Vernaux,** M., Aubinet, M., 2007. | **Heinesch, B., Yernaux,** M., Aubinet, M., 2007. |
| `0083fb2109e58be50aec2eca07fcbfe1230b_page_8.pdf_order_9a6d73a2` | order (`after`) | … the amount from line **2** of **the** Schedule D (Form 1041) | … the amount from line **37a** of Schedule D (Form 1041) |

### B. `absent` tests whose string is also body text (6 tests)

| Test id | Problem |
|---|---|
| `e99fc5946d09541cc7d1b887c328cfe15740cdb9_page_1.pdf_manual_00` | '1' must be absent from the last 2 characters, but the last body line is 'Zlín, duben 2018' |
| `bec1f712cbe509344bff707560d6eed8f05133b3_page_9_header_02` | 'ANEC' must be absent from the first 20 characters, but the first heading of the body is 'ANEC CONCLUSIONS FROM THIS AND EARLIER STUDIES' |
| `6e6caf4cc9a3e734de43f29aabbb9ff0bf6f5487_page_1_header_00` | 'Programs of Graduate Study in the Basic Biological Sciences' is the running header and, per the embedded text, also the title of the page |
| `29019be34d0c59210165af50a8904f749d7c0678_page_1_header_01` | 'FitForFire' is also in a body sentence: '(FitForFire-Aufwärmfibel)' |
| `0ed74b112dde3b3ce5e3a3d6c69a930afaad342c_page_1_processed_pg1_header_00` | 'Physics Minor (Non-Teaching)' is the running header and also the title of the page |
| `e1877d4ffc65bd66a9e5b9a5d2608362ad458c86_page_7_header_01` | 'dodis.ch/31973' is also cited inside footnote 31; the 3 runs that pass left the footnotes out |

**Suggested fix.** For A, replace the expected string with the page's string (or remove the test). For B, remove the test or limit it with `first_n` / `last_n` so that the body text is outside its range.

I can send the corrected JSONL lines, or a pull request on the Hugging Face dataset, if that helps. I also have a page crop for every row.
