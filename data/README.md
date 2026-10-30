# Data

Pinned checksums and provenance of the two public datasets. The data files themselves are never committed; they are downloaded and verified by `airtwin download` (and at image build time).

| File | What it does |
|---|---|
| `checksums.sha256` | SHA-256 of each archive exactly as served by UCI; any mismatch stops the program |
| `raw/` *(ignored)* | Original archives, never modified |
| `processed/` *(ignored)* | Cleaned CSV files written by `airtwin prepare` |

## Datasets

| Key | Dataset | Content | Licence |
|---|---|---|---|
| `uci_air_quality` | [UCI Air Quality (id 360)](https://archive.ics.uci.edu/dataset/360/air+quality) | Hourly responses of 5 low-cost metal-oxide sensors and a co-located certified reference analyzer (CO, NMHC, C6H6, NOx, NO2), plus temperature and humidity, in an Italian city, March 2004 – April 2005. Missing values are tagged `-200`. | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `beijing_multisite` | [UCI Beijing Multi-Site Air Quality (id 501)](https://archive.ics.uci.edu/dataset/501/beijing+multi+site+air+quality+data) | Hourly PM2.5, PM10, SO2, NO2, CO, O3 and weather at 12 Beijing monitoring sites, March 2013 – February 2017. Missing values are `NA`. | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

Notes from the files themselves:

- The UCI Air Quality CSV holds 9,357 dated records (the UCI page lists 9,358 instances). Cleaning reindexes them to a complete hourly range, so absent hours appear as empty rows.
- The Beijing archive also contains files unrelated to the dataset (`data.csv`, `test.csv`, a photo). The loader reads only the 12 `PRSA_Data_*.csv` station files inside the inner `PRSA2017_Data_20130301-20170228.zip`.

## Required citations

Both licences require attribution. Cite the datasets and their introductory papers:

- Vito, S. (2008). *Air Quality* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C59K5F
- De Vito, S., Massera, E., Piga, M., Martinotto, L., & Di Francia, G. (2008). On field calibration of an electronic nose for benzene estimation in an urban pollution monitoring scenario. *Sensors and Actuators B: Chemical*, 129(2), 750–757. https://doi.org/10.1016/j.snb.2007.09.060
- Chen, S. (2017). *Beijing Multi-Site Air Quality* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5RK5G
- Zhang, S., Guo, B., Dong, A., He, J., Xu, Z., & Chen, S. X. (2017). Cautionary tales on air-quality improvement in Beijing. *Proceedings of the Royal Society A*, 473(2205), 20170457. https://doi.org/10.1098/rspa.2017.0457

## How it connects

- `configs/default.yaml` names the URLs, archive files and this checksum file.
- `src/airtwin/data/download.py` downloads and verifies; `uci_loader.py` and `beijing_loader.py` read the archives directly and clean them.
- Site coordinates for the Beijing stations are added with their source when the twin first needs them.
