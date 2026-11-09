# Reporte SQL del World Bank

Generado el 2026-11-09 10:43 desde `world_bank.sqlite`.

## Cobertura por indicador

```sql
SELECT i.indicador, count(*) AS paises_con_dato,
               (SELECT count(*) FROM faltantes f JOIN paises x USING (pais_id)
                WHERE f.indicador_id = i.indicador_id AND x.es_agregado = 0) AS paises_sin_dato,
               min(o.anio) AS anio_mas_antiguo, max(o.anio) AS anio_mas_reciente
        FROM observaciones o JOIN indicadores i USING (indicador_id) JOIN paises p USING (pais_id)
        WHERE p.es_agregado = 0
        GROUP BY i.indicador_id ORDER BY i.indicador
```

| indicador | paises_con_dato | paises_sin_dato | anio_mas_antiguo | anio_mas_reciente |
|---|---|---|---|---|
| Esperanza de vida al nacer (anios) | 217 | 0 | 2024 | 2024 |
| PIB per capita (US$ corrientes) | 214 | 3 | 2011 | 2025 |
| Personas que usan Internet (% poblacion) | 213 | 4 | 1990 | 2025 |
| Poblacion total | 217 | 0 | 2025 | 2025 |

## Los 10 países con mayor PIB per cápita (US$)

```sql
SELECT p.pais, o.anio, round(o.valor, 2) AS pib_per_capita
        FROM observaciones o JOIN paises p USING (pais_id)
        WHERE o.indicador_id = 'NY.GDP.PCAP.CD' AND p.es_agregado = 0
        ORDER BY o.valor DESC LIMIT 10
```

| pais | anio | pib_per_capita |
|---|---|---|
| Monaco | 2024 | 288001.6 |
| Liechtenstein | 2024 | 220167.2 |
| Luxembourg | 2025 | 147252.2 |
| Bermuda | 2024 | 142250.4 |
| Ireland | 2025 | 131592.5 |
| Switzerland | 2025 | 114769.0 |
| Cayman Islands | 2024 | 104292.9 |
| Singapore | 2025 | 98814.0 |
| Iceland | 2025 | 98323.5 |
| Norway | 2025 | 94594.2 |

## México en los 4 indicadores

```sql
SELECT i.indicador, o.anio, round(o.valor, 2) AS valor
        FROM observaciones o JOIN indicadores i USING (indicador_id)
        WHERE o.pais_id = 'MX' ORDER BY i.indicador
```

| indicador | anio | valor |
|---|---|---|
| Esperanza de vida al nacer (anios) | 2024 | 75.0 |
| PIB per capita (US$ corrientes) | 2025 | 13889.2 |
| Personas que usan Internet (% poblacion) | 2024 | 83.0 |
| Poblacion total | 2025 | 131946900.0 |
