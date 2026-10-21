# Bloembollen-site

Een kleine FastAPI-app met SQLite en lokale foto-opslag. De applicatie draait op
poort 8000 en bewaart alle blijvende gegevens in `/data`.

## Starten

Het `docker-compose.yml` gebruikt de image `ghcr.io/donixon/bloembollen-site:latest`
en kan los van de repository worden gekopieerd:

```bash
docker compose pull
ADMIN_TOKEN='kies-een-lang-geheim' docker compose up -d
```

Zelf bouwen vanuit de broncode kan met `docker build -t bloembollen-site .`.

Open daarna `http://localhost:8000`. De gezondheidscontrole staat op
`http://localhost:8000/api/health`.

## Omgevingsvariabelen

| Variabele | Standaard | Betekenis |
|---|---:|---|
| `DATA_DIR` | `/data` | Map voor `app.db` en `uploads/` |
| `ADMIN_TOKEN` | leeg | Token voor `DELETE /api/posts/{id}`; verwijderen staat uit als deze leeg is |
| `COORD_DECIMALS` | `2` | Aantal decimalen waarop coördinaten worden afgerond (0 t/m 6) |
| `MAX_UPLOAD_MB` | `15` | Maximale uploadgrootte in MB |

Gebruik in productie een lang, willekeurig `ADMIN_TOKEN` en leg dit niet vast in
de repository.

## Testen en linten

Maak desgewenst een virtuele omgeving, installeer de ontwikkelafhankelijkheden en
voer de controles uit:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check app tests
```

## Back-up

Stop voor een consistente back-up eerst de container en archiveer daarna het
named volume `bloembollen-data` (de volledige inhoud van `/data`). Daarin staan
zowel de SQLite-database als alle originele, verwerkte foto's en thumbnails.
Herstellen bestaat uit het terugplaatsen van die volledige map/volume-inhoud
voordat de container opnieuw wordt gestart.
