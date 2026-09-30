-- AdWanted (respondent level, 2026 Q2) <-> RAJAR (published E-Demogs) lineage recipes
-- Schema: HACKATHON_TEAM_GINGER_DB.RAJAR (select * views over SRC_RAJAR_SHARE.RAJAR)
--
-- Rules verified against published 2026 Q2 figures:
--   * AdWanted column names are case-sensitive: always double-quote them ("StationID", "Weight", ...).
--   * Reach (000s)  = SUM("Weight") / 10000 over DISTINCT respondents aged 15+.
--   * Hours         = SUM(IMPACTS) / 4 from ADWANTED_DIARY_IMPACTS for ONE SGP_ID.
--   * ADWANTED_DIARY_IMPACTS has one row per diary claim PER SGP the station belongs to,
--     so always filter to a single SGP_ID (or DISTINCT on the diary grain) before summing.
--   * Station code = platform prefix * 10000 + base station id (100057 = AM/FM, 200057 = DAB, 400057 = online).
--   * RELEASE_NUMBER 202602 = 2026 Q2 = the AdWanted quarter.

USE SCHEMA HACKATHON_TEAM_GINGER_DB.RAJAR;


-- 1. Enrich every diary claim with station, platform, region, genre and respondent demographics
CREATE OR REPLACE TEMPORARY VIEW DIARY_ENRICHED AS
SELECT
    d."MTPersonNo"                     AS person_no,
    d."StationID"                      AS station_code,
    MOD(d."StationID", 10000)          AS base_station_id,
    DECODE(d."platform", 1, 'AM/FM', 2, 'DAB', 3, 'DTV', 4, 'Online', 5, 'Online (DT)',
                         7, 'Smart speaker', 8, 'Smart speaker (DT)')          AS platform,
    d."Day"                            AS day_of_week,
    t."StartTime"::TIME                AS slot_start,
    t."EndTime"::TIME                  AS slot_end,
    d."wherelistened"                  AS where_listened_code,
    s.STATION_NAME,
    s.STATION_PLATFORM_NAME,
    s.GENRE,
    s.REGION_LONDON, s.REGION_NORTH_WEST, s.REGION_SCOTLAND_ANY,
    p."age"                            AS age,
    DECODE(p."sex", 1, 'Men', 2, 'Women')                                       AS gender,
    DECODE(p."class", 1, 'A', 2, 'B', 3, 'C1', 4, 'C2', 5, 'D', 6, 'E')         AS social_grade,
    IFF(p."class" <= 3, 'ABC1', 'C2DE')                                         AS social_segment,
    p."Weight" / 10                    AS weight_persons
FROM ADWANTED_DIARY_2026_Q2 d
JOIN ADWANTED_PERSON_2026_Q2 p        ON p."MTPersonNo" = d."MTPersonNo"
JOIN ADWANTED_TIME_SEGMENT_2026_Q2 t  ON t."MTQTRCode"  = d."MTQtrcode"
LEFT JOIN (
    SELECT *, (REGION_CENTRAL_SCOTLAND OR REGION_NORTH_SCOTLAND) AS REGION_SCOTLAND_ANY
    FROM STATION_ATTRIBUTES
) s ON s.STATION_CODE = d."StationID"          -- ~95% of diary stations match; the rest are new stations, use SGP_STATION
WHERE p."age" >= 15;


-- 2. Weighted weekly reach for a radio brand (SGP) - matches published WEEKLY_REACH exactly
--    BBC Radio 2: 12,367k (AdWanted) vs 12,367k (WEEKLY_REACH, report 1901, release 202602)
WITH brand AS (
    SELECT RSL_IDS FROM SGP_STATION WHERE DESCRIPTION = 'BBC Radio 2'
), listeners AS (
    SELECT DISTINCT d."MTPersonNo"
    FROM ADWANTED_DIARY_2026_Q2 d
    JOIN brand b ON ARRAY_CONTAINS(d."StationID"::VARIANT, b.RSL_IDS)
)
SELECT ROUND(SUM(p."Weight") / 10000) AS weekly_reach_000s,
       COUNT(*)                        AS unweighted_sample
FROM listeners l
JOIN ADWANTED_PERSON_2026_Q2 p ON p."MTPersonNo" = l."MTPersonNo"
WHERE p."age" >= 15;


-- 3. Bridge: AdWanted brand (SGP) -> RAJAR report -> owner + published figures
--    Match on identical station set first, then fall back to exact name.
CREATE OR REPLACE TEMPORARY VIEW SGP_REPORT_BRIDGE AS
WITH g AS (
    SELECT SGP_ID, DESCRIPTION, IS_AIRTIME, IS_SPONSORSHIP,
           ARRAY_TO_STRING(ARRAY_SORT(ARRAY_DISTINCT(RSL_IDS::ARRAY)), ',') AS station_set
    FROM SGP_STATION
), r AS (
    SELECT REPORT_NUMBER, REPORT_NAME,
           ARRAY_TO_STRING(ARRAY_SORT(ARRAY_DISTINCT(STATION_CODES::ARRAY)), ',') AS station_set
    FROM REPORT_STATIONS
), candidates AS (
    SELECT g.SGP_ID, g.DESCRIPTION, r.REPORT_NUMBER, r.REPORT_NAME,
           IFF(g.station_set = r.station_set, 'station_set', 'name') AS match_type,
           IFF(g.station_set = r.station_set, 1, 2)
             + IFF(UPPER(TRIM(g.DESCRIPTION)) = UPPER(TRIM(r.REPORT_NAME)), 0, 0.5) AS rank_score
    FROM g JOIN r
      ON g.station_set = r.station_set
      OR UPPER(TRIM(g.DESCRIPTION)) = UPPER(TRIM(r.REPORT_NAME))
)
SELECT SGP_ID, DESCRIPTION, REPORT_NUMBER, REPORT_NAME, match_type
FROM candidates
QUALIFY ROW_NUMBER() OVER (PARTITION BY SGP_ID ORDER BY rank_score, REPORT_NUMBER) = 1;

SELECT b.SGP_ID, b.DESCRIPTION, b.match_type,
       b.REPORT_NUMBER, h.PARENT_ORG, h.IS_NATIONAL, h.REPORT_AS_BRAND,
       w.WEEKLY_REACH_000S, w.TOTAL_HOURS, w.MARKET_SHARE
FROM SGP_REPORT_BRIDGE b
JOIN REPORT_HIERARCHY h ON h.REPORT_NUMBER = b.REPORT_NUMBER
LEFT JOIN WEEKLY_REACH w ON w.REPORT_NUMBER = b.REPORT_NUMBER AND w.RELEASE_NUMBER = 202602
WHERE h.PARENT_ORG LIKE 'GLOBAL%'
ORDER BY w.WEEKLY_REACH_000S DESC NULLS LAST
LIMIT 20;


-- 4. Custom demographic cut from AdWanted, lined up against the published demographic row
--    DEMOGRAPHIC_ATTRIBUTES turns a published demographic name into the age/gender/segment rule.
WITH demo AS (
    SELECT DEMOGRAPHIC, AGE_FROM, AGE_TO, GENDER, SEGMENT
    FROM DEMOGRAPHIC_ATTRIBUTES WHERE DEMOGRAPHIC = 'Women 25-34'
), listeners AS (
    SELECT DISTINCT d."MTPersonNo"
    FROM ADWANTED_DIARY_2026_Q2 d
    JOIN SGP_STATION g ON g.DESCRIPTION = 'BBC Radio 2'
                      AND ARRAY_CONTAINS(d."StationID"::VARIANT, g.RSL_IDS)
)
SELECT demo.DEMOGRAPHIC,
       ROUND(SUM(p."Weight") / 10000) AS adwanted_reach_000s,
       COUNT(*)                        AS unweighted_sample,
       ANY_VALUE(w.WEEKLY_REACH_000S)  AS published_reach_000s
FROM listeners l
JOIN ADWANTED_PERSON_2026_Q2 p ON p."MTPersonNo" = l."MTPersonNo"
JOIN demo
  ON p."age" BETWEEN demo.AGE_FROM AND COALESCE(demo.AGE_TO, 200)
 AND (demo.GENDER IS NULL OR demo.GENDER = '' OR demo.GENDER = DECODE(p."sex", 1, 'Men', 2, 'Women'))
 AND (demo.SEGMENT IS NULL OR demo.SEGMENT = '' OR demo.SEGMENT = IFF(p."class" <= 3, 'ABC1', 'C2DE'))
LEFT JOIN WEEKLY_REACH_BY_DEMOGRAPHIC w
  ON w.REPORT_NUMBER = 1901 AND w.RELEASE_NUMBER = 202602 AND w.DEMOGRAPHIC = demo.DEMOGRAPHIC
GROUP BY demo.DEMOGRAPHIC;


-- 5. Competitive set: comparable stations map back to reports via COMPARABLE_NUMBER - 50000
SELECT c.REPORT_NAME, c.COMPARABLE_NAME, h.PARENT_ORG, c.WEEKLY_REACH_000S, c.MARKET_SHARE
FROM WEEKLY_REACH_COMPARABLES c
LEFT JOIN REPORT_HIERARCHY h ON h.REPORT_NUMBER = c.COMPARABLE_NUMBER - 50000
WHERE c.RELEASE_NUMBER = 202602 AND c.REPORT_NUMBER = 1901
ORDER BY c.WEEKLY_REACH_000S DESC
LIMIT 15;
