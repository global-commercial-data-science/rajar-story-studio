-- =====================================================================================
-- AdWanted listening star schema  ->  HACKATHON_TEAM_GINGER_DB.ANALYTICS
-- Source: HACKATHON_TEAM_GINGER_DB.RAJAR (views over SRC_RAJAR_SHARE.RAJAR), 2026 Q2
-- Idempotent: safe to re-run. Build time ~2-3 min on an XSMALL warehouse.
--
-- Rules (each verified against published RAJAR 2026 Q2 figures):
--   weight_persons   = "Weight" / 10                     (respondent weight in people)
--   quarter_hours    = IFF(halfhour slot, 2, 1) / "claimcount"
--                      (claimcount = number of stations claimed in the same slot)
--   weighted_hours   = weight_persons * quarter_hours / 4
--   weekly reach 000s = SUM of weight_persons over DISTINCT respondents / 1000
--   Only respondents aged 15+ are loaded into the facts (RAJAR universe).
-- =====================================================================================

USE ROLE HACKATHON_TEAM_GINGER;
USE WAREHOUSE HACKATHON_TEAM_GINGER_BASIC_WH;
USE SCHEMA HACKATHON_TEAM_GINGER_DB.ANALYTICS;


-- -------------------------------------------------------------------------------------
-- DIM_TIME_SLOT : 84 diary time slots
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE DIM_TIME_SLOT
COMMENT = 'One row per AdWanted diary time slot (84). Quarter-hours from 06:00 to midnight, half-hours overnight.'
AS
SELECT
    "MTQTRCode"::NUMBER(38,0)                      AS slot_code,
    "StartTime"::TIME                              AS slot_start,
    "EndTime"::TIME                                AS slot_end,
    TO_CHAR("StartTime", 'HH24:MI') || '-' || TO_CHAR("EndTime", 'HH24:MI') AS slot_label,
    HOUR("StartTime")                              AS hour_of_day,
    "halfhour"                                     AS is_half_hour,
    IFF("halfhour", 2, 1)                          AS slot_quarter_hours,
    CASE
        WHEN HOUR("StartTime") BETWEEN 6  AND 9  THEN 'Breakfast'
        WHEN HOUR("StartTime") BETWEEN 10 AND 15 THEN 'Daytime'
        WHEN HOUR("StartTime") BETWEEN 16 AND 18 THEN 'Drive'
        WHEN HOUR("StartTime") BETWEEN 19 AND 23 THEN 'Evening'
        ELSE 'Overnight'
    END                                            AS daypart,
    CASE
        WHEN HOUR("StartTime") BETWEEN 6  AND 9  THEN 1
        WHEN HOUR("StartTime") BETWEEN 10 AND 15 THEN 2
        WHEN HOUR("StartTime") BETWEEN 16 AND 18 THEN 3
        WHEN HOUR("StartTime") BETWEEN 19 AND 23 THEN 4
        ELSE 5
    END                                            AS daypart_order,
    -- RAJAR published 3-hour time bands (DAYPART_REACH_* TIME_BAND values)
    CASE
        WHEN HOUR("StartTime") BETWEEN 6  AND 8  THEN '06.00-09.00'
        WHEN HOUR("StartTime") BETWEEN 9  AND 11 THEN '09.00-12.00'
        WHEN HOUR("StartTime") BETWEEN 12 AND 14 THEN '12.00-15.00'
        WHEN HOUR("StartTime") BETWEEN 15 AND 17 THEN '15.00-18.00'
        WHEN HOUR("StartTime") BETWEEN 18 AND 20 THEN '18.00-21.00'
        WHEN HOUR("StartTime") BETWEEN 21 AND 23 THEN '21.00-24.00'
        ELSE '24.00-06.00'
    END                                            AS rajar_time_band
FROM HACKATHON_TEAM_GINGER_DB.RAJAR.ADWANTED_TIME_SEGMENT_2026_Q2;


-- -------------------------------------------------------------------------------------
-- DIM_RESPONDENT : one row per AdWanted respondent
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE DIM_RESPONDENT
COMMENT = 'One row per AdWanted 2026 Q2 respondent with survey weight and decoded demographics.'
AS
SELECT
    "MTPersonNo"::NUMBER(38,0)                     AS respondent_id,
    "Weight"                                       AS weight_raw,
    "Weight" / 10                                  AS weight_persons,
    "age"                                          AS age,
    "age" >= 15                                    AS is_adult_15_plus,
    CASE
        WHEN "age" < 15 THEN 'Under 15'
        WHEN "age" <= 24 THEN '15-24'
        WHEN "age" <= 34 THEN '25-34'
        WHEN "age" <= 44 THEN '35-44'
        WHEN "age" <= 54 THEN '45-54'
        WHEN "age" <= 64 THEN '55-64'
        ELSE '65+'
    END                                            AS age_band,
    DECODE("sex", 1, 'Men', 2, 'Women')            AS gender,
    DECODE("class", 1, 'A', 2, 'B', 3, 'C1', 4, 'C2', 5, 'D', 6, 'E') AS social_grade,
    IFF("class" <= 3, 'ABC1', 'C2DE')              AS social_segment,
    DECODE("ilrRegions", 1, 'London', 2, 'Midlands', 3, 'North West', 4, 'Yorkshire',
                         5, 'North East', 6, 'Central Scotland', 7, 'North Scotland', 8, 'South',
                         9, 'East of England', 10, 'South West', 11, 'Ulster', 12, 'Border',
                         13, 'West', 14, 'Wales', 15, 'Channel Islands', 'Unassigned') AS ilr_region,
    "bbcregion"                                    AS bbc_region_code,
    "itvarea2010"                                  AS itv_area_code,
    "householdsize"                                AS household_size,
    "children014"                                  AS children_0_14_count,
    "children014" > 0                              AS has_children_0_14,
    "working"                                      AS working_status_code,
    "mosaic6"                                      AS mosaic_type_code,
    "AcornGroup2023"                               AS acorn_group_code,
    "useWebsiteOrApp_globalPlayer"                 AS uses_global_player,
    "useWebsiteOrApp_bbcSounds"                    AS uses_bbc_sounds,
    "useWebsiteOrApp_radioplayer"                  AS uses_radioplayer,
    "useWebsiteOrApp_capital"                      AS uses_capital_app,
    "useWebsiteOrApp_heart"                        AS uses_heart_app,
    "useWebsiteOrApp_kiss"                         AS uses_kiss_app,
    "useWebsiteOrApp_magic"                        AS uses_magic_app,
    "useWebsiteOrApp_absoluteRadio"                AS uses_absolute_radio_app,
    "useWebsiteOrApp_talksport"                    AS uses_talksport_app
FROM HACKATHON_TEAM_GINGER_DB.RAJAR.ADWANTED_PERSON_2026_Q2;


-- -------------------------------------------------------------------------------------
-- DIM_STATION : one row per station x platform code (every code seen in the diary included)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE DIM_STATION
COMMENT = 'One row per RAJAR station code. A station code is platform prefix * 10000 + base station id, so each station appears once per platform.'
AS
WITH codes AS (
    SELECT STATION_CODE::NUMBER(38,0) AS station_code FROM HACKATHON_TEAM_GINGER_DB.RAJAR.STATION_ATTRIBUTES
    UNION
    SELECT DISTINCT "StationID"::NUMBER(38,0) FROM HACKATHON_TEAM_GINGER_DB.RAJAR.ADWANTED_DIARY_2026_Q2
), smallest_brand AS (
    -- best available name for codes missing from STATION_ATTRIBUTES: the smallest brand containing it
    SELECT f.value::NUMBER AS station_code, g.DESCRIPTION
    FROM HACKATHON_TEAM_GINGER_DB.RAJAR.SGP_STATION g, LATERAL FLATTEN(g.RSL_IDS) f
    QUALIFY ROW_NUMBER() OVER (PARTITION BY f.value::NUMBER ORDER BY ARRAY_SIZE(g.RSL_IDS), g.SGP_ID) = 1
)
SELECT
    c.station_code,
    MOD(c.station_code, 10000)                     AS base_station_id,
    DECODE(FLOOR(c.station_code / 10000), 10, 'AM/FM', 20, 'DAB', 30, 'DTV', 40, 'Online',
           41, 'Online', 42, 'Smart speaker', 43, 'Smart speaker', 'Other') AS platform,
    COALESCE(INITCAP(s.STATION_NAME), b.DESCRIPTION, 'Station ' || c.station_code) AS station_name,
    s.STATION_PLATFORM_NAME                        AS station_platform_name,
    s.STATION_CODE IS NOT NULL                     AS is_in_rajar_station_list,
    NULLIF(s.GENRE, '')                            AS genre,
    COALESCE(s.GROUP_ALL_BBC_1660, FALSE)                  AS is_bbc,
    COALESCE(s.GROUP_ALL_COMMERCIAL_1670, FALSE)           AS is_commercial,
    COALESCE(s.GROUP_ALL_NATIONAL_COMMERCIAL_1680, FALSE)  AS is_national_commercial,
    COALESCE(s.GROUP_ALL_LOCAL_COMMERCIAL_1691, FALSE)     AS is_local_commercial,
    COALESCE(s.GROUP_BBC_LOCAL_REGIONAL_1905, FALSE)       AS is_bbc_local_regional,
    COALESCE(s.REGION_LONDON, FALSE)            AS region_london,
    COALESCE(s.REGION_MIDLANDS, FALSE)          AS region_midlands,
    COALESCE(s.REGION_NORTH_WEST, FALSE)        AS region_north_west,
    COALESCE(s.REGION_YORKSHIRE, FALSE)         AS region_yorkshire,
    COALESCE(s.REGION_NORTH_EAST, FALSE)        AS region_north_east,
    COALESCE(s.REGION_CENTRAL_SCOTLAND, FALSE)  AS region_central_scotland,
    COALESCE(s.REGION_NORTH_SCOTLAND, FALSE)    AS region_north_scotland,
    COALESCE(s.REGION_SOUTH, FALSE)             AS region_south,
    COALESCE(s.REGION_EAST_OF_ENGLAND, FALSE)   AS region_east_of_england,
    COALESCE(s.REGION_SOUTH_WEST, FALSE)        AS region_south_west,
    COALESCE(s.REGION_ULSTER, FALSE)            AS region_ulster,
    COALESCE(s.REGION_BORDER, FALSE)            AS region_border,
    COALESCE(s.REGION_WEST, FALSE)              AS region_west,
    COALESCE(s.REGION_WALES, FALSE)             AS region_wales,
    COALESCE(s.REGION_CHANNEL_ISLANDS, FALSE)   AS region_channel_islands
FROM codes c
LEFT JOIN HACKATHON_TEAM_GINGER_DB.RAJAR.STATION_ATTRIBUTES s ON s.STATION_CODE = c.station_code
LEFT JOIN smallest_brand b ON b.station_code = c.station_code;


-- -------------------------------------------------------------------------------------
-- DIM_BRAND : AdWanted brands / sales groups, bridged to RAJAR reports and owners
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE DIM_BRAND
COMMENT = 'One row per AdWanted brand or sales group (SGP). Linked to the matching RAJAR report (same station set, else same name) for owner and published 2026 Q2 figures.'
AS
WITH g AS (
    SELECT *, ARRAY_TO_STRING(ARRAY_SORT(ARRAY_DISTINCT(RSL_IDS::ARRAY)), ',') AS station_set
    FROM HACKATHON_TEAM_GINGER_DB.RAJAR.SGP_STATION
), r AS (
    SELECT REPORT_NUMBER, REPORT_NAME,
           ARRAY_TO_STRING(ARRAY_SORT(ARRAY_DISTINCT(STATION_CODES::ARRAY)), ',') AS station_set
    FROM HACKATHON_TEAM_GINGER_DB.RAJAR.REPORT_STATIONS
), bridge AS (
    SELECT g.SGP_ID, r.REPORT_NUMBER, r.REPORT_NAME,
           IFF(g.station_set = r.station_set, 'Same station set', 'Same name') AS match_type
    FROM g JOIN r
      ON g.station_set = r.station_set
      OR UPPER(TRIM(g.DESCRIPTION)) = UPPER(TRIM(r.REPORT_NAME))
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY g.SGP_ID
        ORDER BY IFF(g.station_set = r.station_set, 1, 2),
                 IFF(UPPER(TRIM(g.DESCRIPTION)) = UPPER(TRIM(r.REPORT_NAME)), 0, 1),
                 r.REPORT_NUMBER) = 1
)
SELECT
    g.SGP_ID::NUMBER(38,0)                         AS brand_id,
    g.DESCRIPTION                                  AS brand_name,
    ARRAY_SIZE(g.RSL_IDS)                          AS station_code_count,
    g.IS_AIRTIME                                   AS is_airtime_package,
    g.IS_SPONSORSHIP                               AS is_sponsorship_package,
    g.IS_TRADED                                    AS is_traded,
    g.IS_ON_RAJAR                                  AS is_on_rajar,
    b.REPORT_NUMBER                                AS rajar_report_number,
    b.REPORT_NAME                                  AS rajar_report_name,
    COALESCE(b.match_type, 'No RAJAR report')      AS rajar_match_type,
    COALESCE(NULLIF(h.PARENT_ORG, ''), 'UNKNOWN')  AS owner,
    h.IS_NATIONAL                                  AS is_national,
    h.IS_LOCAL                                     AS is_local,
    h.IS_COMMERCIAL                                AS is_commercial,
    h.REPORT_AS_STATION                            AS report_is_station,
    h.REPORT_AS_BRAND                              AS report_is_brand,
    h.REPORT_AS_NETWORK                            AS report_is_network,
    h.REPORT_AS_REGION                             AS report_is_region,
    w.SURVEY_PERIOD                                AS published_survey_period,
    w.WEEKLY_REACH_000S                            AS published_weekly_reach_000s,
    w.TOTAL_HOURS                                  AS published_total_hours_000s,
    w.MARKET_SHARE                                 AS published_market_share_pct
FROM g
LEFT JOIN bridge b ON b.SGP_ID = g.SGP_ID
LEFT JOIN HACKATHON_TEAM_GINGER_DB.RAJAR.REPORT_HIERARCHY h ON h.REPORT_NUMBER = b.REPORT_NUMBER
LEFT JOIN HACKATHON_TEAM_GINGER_DB.RAJAR.WEEKLY_REACH w
       ON w.REPORT_NUMBER = b.REPORT_NUMBER AND w.RELEASE_NUMBER = 202602;


-- -------------------------------------------------------------------------------------
-- BRIDGE_BRAND_STATION : which station codes count towards which brand
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE BRIDGE_BRAND_STATION
COMMENT = 'Many-to-many map of brand (SGP) to station code, flattened from SGP_STATION.RSL_IDS.'
AS
SELECT DISTINCT g.SGP_ID::NUMBER(38,0) AS brand_id, f.value::NUMBER(38,0) AS station_code
FROM HACKATHON_TEAM_GINGER_DB.RAJAR.SGP_STATION g, LATERAL FLATTEN(g.RSL_IDS) f;


-- -------------------------------------------------------------------------------------
-- FACT_LISTENING : one row per diary listening claim, adults 15+
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE FACT_LISTENING
CLUSTER BY (station_code)
COMMENT = 'One row per AdWanted diary listening claim (respondent x station code x day x time slot), adults 15+. Use for station, platform, daypart and all-radio questions.'
AS
SELECT
    ROW_NUMBER() OVER (ORDER BY d."MTPersonNo", d."Day", d."MTQtrcode", d."StationID") AS listening_id,
    d."MTPersonNo"::NUMBER(38,0)                   AS respondent_id,
    d."StationID"::NUMBER(38,0)                    AS station_code,
    d."MTQtrcode"::NUMBER(38,0)                    AS slot_code,
    d."Day"                                        AS day_code,
    DECODE(d."Day", 1, 'Monday', 2, 'Tuesday', 3, 'Wednesday', 4, 'Thursday',
                    5, 'Friday', 6, 'Saturday', 7, 'Sunday') AS day_name,
    IFF(d."Day" <= 5, 'Monday-Friday', DECODE(d."Day", 6, 'Saturday', 7, 'Sunday')) AS day_band,
    d."Day" >= 6                                   AS is_weekend,
    d."platform"                                   AS platform_code,
    DECODE(d."platform", 1, 'AM/FM', 2, 'DAB', 3, 'DTV', 4, 'Online', 5, 'Online',
                         7, 'Smart speaker', 8, 'Smart speaker', 'Other') AS platform,
    d."wherelistened"                              AS where_listened_code,
    d."claimcount"                                 AS stations_claimed_in_slot,
    IFF(t."halfhour", 2, 1) / d."claimcount"       AS quarter_hours,
    p."Weight" / 10                                AS weight_persons,
    p."Weight" / 10 * IFF(t."halfhour", 2, 1) / d."claimcount" / 4 AS weighted_hours,
    -- helper keys for exact weighted reach: SUM(DISTINCT reach_key) - SUM(DISTINCT reach_base) = SUM(weight_raw) per distinct respondent
    d."MTPersonNo"::NUMBER(38,0) * 100000000               AS reach_base,
    d."MTPersonNo"::NUMBER(38,0) * 100000000 + p."Weight"   AS reach_key
FROM HACKATHON_TEAM_GINGER_DB.RAJAR.ADWANTED_DIARY_2026_Q2 d
JOIN HACKATHON_TEAM_GINGER_DB.RAJAR.ADWANTED_PERSON_2026_Q2 p       ON p."MTPersonNo" = d."MTPersonNo"
JOIN HACKATHON_TEAM_GINGER_DB.RAJAR.ADWANTED_TIME_SEGMENT_2026_Q2 t ON t."MTQTRCode"  = d."MTQtrcode"
WHERE p."age" >= 15;


-- -------------------------------------------------------------------------------------
-- FACT_BRAND_LISTENING : each claim repeated once per brand it counts towards
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE FACT_BRAND_LISTENING
CLUSTER BY (brand_id)
COMMENT = 'FACT_LISTENING claims repeated once per brand (SGP) the station belongs to. ALWAYS filter to brand(s) and group by brand; summing across brands double counts.'
AS
SELECT
    f.listening_id, bs.brand_id, f.respondent_id, f.station_code, f.slot_code,
    f.day_code, f.day_name, f.day_band, f.is_weekend, f.platform_code, f.platform,
    f.where_listened_code, f.stations_claimed_in_slot, f.quarter_hours,
    f.weight_persons, f.weighted_hours, f.reach_base, f.reach_key
FROM FACT_LISTENING f
JOIN BRIDGE_BRAND_STATION bs ON bs.station_code = f.station_code;


-- -------------------------------------------------------------------------------------
-- Keys (informational in Snowflake, but used by tools and the semantic view)
-- -------------------------------------------------------------------------------------
ALTER TABLE DIM_TIME_SLOT        ADD PRIMARY KEY (slot_code);
ALTER TABLE DIM_RESPONDENT       ADD PRIMARY KEY (respondent_id);
ALTER TABLE DIM_STATION          ADD PRIMARY KEY (station_code);
ALTER TABLE DIM_BRAND            ADD PRIMARY KEY (brand_id);
ALTER TABLE FACT_LISTENING       ADD PRIMARY KEY (listening_id);
ALTER TABLE FACT_BRAND_LISTENING ADD PRIMARY KEY (listening_id, brand_id);
ALTER TABLE FACT_LISTENING       ADD FOREIGN KEY (respondent_id) REFERENCES DIM_RESPONDENT (respondent_id);
ALTER TABLE FACT_LISTENING       ADD FOREIGN KEY (station_code)  REFERENCES DIM_STATION (station_code);
ALTER TABLE FACT_LISTENING       ADD FOREIGN KEY (slot_code)     REFERENCES DIM_TIME_SLOT (slot_code);
ALTER TABLE FACT_BRAND_LISTENING ADD FOREIGN KEY (brand_id)      REFERENCES DIM_BRAND (brand_id);
ALTER TABLE FACT_BRAND_LISTENING ADD FOREIGN KEY (respondent_id) REFERENCES DIM_RESPONDENT (respondent_id);
ALTER TABLE FACT_BRAND_LISTENING ADD FOREIGN KEY (station_code)  REFERENCES DIM_STATION (station_code);
ALTER TABLE FACT_BRAND_LISTENING ADD FOREIGN KEY (slot_code)     REFERENCES DIM_TIME_SLOT (slot_code);
