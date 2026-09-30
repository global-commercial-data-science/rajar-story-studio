-- =====================================================================================
-- Schema value vector store  ->  HACKATHON_TEAM_GINGER_DB.ANALYTICS.SCHEMA_VECTORS
--
-- One row per distinct combination of categorical values in each ANALYTICS table,
-- written as an English sentence (CONTEXT), embedded (VECTOR), with the matching
-- column/value filters (FILTERS, keys are TABLE.COLUMN) and a ready WHERE fragment
-- (FILTER_SQL). An agent embeds the user's question, finds the nearest rows and uses
-- their filters to build SQL.
--
--   ENTRY_TYPE = 'combination'   distinct combination of the table's categorical columns
--   ENTRY_TYPE = 'profile'       respondent combination x station listened to (FACT_LISTENING)
--   ENTRY_TYPE = 'single_value'  one column = one value, for short questions
--
-- Embedding model: snowflake-arctic-embed-m-v1.5 (768 dims). Idempotent.
-- =====================================================================================

USE ROLE HACKATHON_TEAM_GINGER;
USE WAREHOUSE HACKATHON_TEAM_GINGER_BASIC_WH;
USE SCHEMA HACKATHON_TEAM_GINGER_DB.ANALYTICS;


-- Turns {"DIM_RESPONDENT.GENDER": "Women", "DIM_RESPONDENT.USES_BBC_SOUNDS": true}
-- into DIM_RESPONDENT.GENDER = 'Women' AND DIM_RESPONDENT.USES_BBC_SOUNDS = TRUE
CREATE OR REPLACE FUNCTION FILTERS_TO_SQL(F OBJECT)
RETURNS STRING
LANGUAGE JAVASCRIPT
COMMENT = 'Converts a SCHEMA_VECTORS.FILTERS object into a SQL WHERE fragment.'
AS $$
  return Object.keys(F).sort().map(function (k) {
    var v = F[k];
    if (v === null) return k + ' IS NULL';
    if (typeof v === 'boolean') return k + ' = ' + (v ? 'TRUE' : 'FALSE');
    if (typeof v === 'number') return k + ' = ' + v;
    return k + " = '" + String(v).replace(/'/g, "''") + "'";
  }).join(' AND ');
$$;


-- -------------------------------------------------------------------------------------
-- Stage 1: sentences + filters (no embeddings yet)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TEMPORARY TABLE SCHEMA_VECTOR_TEXT (
    TABLE_NAME STRING, ENTRY_TYPE STRING, CONTEXT STRING, FILTERS OBJECT, SOURCE_ROWS NUMBER
);

-- Helper view: respondent demographic sentence + filters (every combination)
CREATE OR REPLACE TEMPORARY VIEW RESPONDENT_PHRASE AS
SELECT
    respondent_id,
    gender || ', ' ||
        IFF(age_band = 'Under 15', 'aged under 15', 'aged ' || age_band) ||
        ', social grade ' || social_grade || ' (' || social_segment || ')' ||
        ', living in ' || IFF(ilr_region = 'Unassigned', 'an unassigned region', ilr_region) ||
        ', ' || IFF(has_children_0_14, 'with children aged 0-14', 'no children aged 0-14') ||
        ', household of ' || household_size || IFF(household_size >= 5, ' or more', '') ||
            IFF(household_size = 1, ' person', ' people') ||
        ', ' || COALESCE('uses ' || NULLIF(ARRAY_TO_STRING(ARRAY_CONSTRUCT_COMPACT(
                IFF(uses_global_player, 'Global Player', NULL),
                IFF(uses_bbc_sounds, 'BBC Sounds', NULL),
                IFF(uses_radioplayer, 'Radioplayer', NULL),
                IFF(uses_capital_app, 'the Capital app', NULL),
                IFF(uses_heart_app, 'the Heart app', NULL),
                IFF(uses_kiss_app, 'the Kiss app', NULL),
                IFF(uses_magic_app, 'the Magic app', NULL),
                IFF(uses_absolute_radio_app, 'the Absolute Radio app', NULL),
                IFF(uses_talksport_app, 'the talkSPORT app', NULL)), ', '), ''),
            'uses none of the listed radio apps') AS phrase,
    OBJECT_CONSTRUCT(
        'DIM_RESPONDENT.GENDER', gender,
        'DIM_RESPONDENT.AGE_BAND', age_band,
        'DIM_RESPONDENT.SOCIAL_GRADE', social_grade,
        'DIM_RESPONDENT.SOCIAL_SEGMENT', social_segment,
        'DIM_RESPONDENT.ILR_REGION', ilr_region,
        'DIM_RESPONDENT.HAS_CHILDREN_0_14', has_children_0_14,
        'DIM_RESPONDENT.HOUSEHOLD_SIZE', household_size,
        'DIM_RESPONDENT.USES_GLOBAL_PLAYER', uses_global_player,
        'DIM_RESPONDENT.USES_BBC_SOUNDS', uses_bbc_sounds,
        'DIM_RESPONDENT.USES_RADIOPLAYER', uses_radioplayer,
        'DIM_RESPONDENT.USES_CAPITAL_APP', uses_capital_app,
        'DIM_RESPONDENT.USES_HEART_APP', uses_heart_app,
        'DIM_RESPONDENT.USES_KISS_APP', uses_kiss_app,
        'DIM_RESPONDENT.USES_MAGIC_APP', uses_magic_app,
        'DIM_RESPONDENT.USES_ABSOLUTE_RADIO_APP', uses_absolute_radio_app,
        'DIM_RESPONDENT.USES_TALKSPORT_APP', uses_talksport_app) AS filters
FROM DIM_RESPONDENT;

-- Helper view: fact-level (when / how) sentence + filters
CREATE OR REPLACE TEMPORARY VIEW LISTENING_PHRASE AS
SELECT DISTINCT
    day_name, day_band, is_weekend, platform, where_listened_code,
    'Listening on ' || day_name || ' (' || day_band || ', ' || IFF(is_weekend, 'weekend', 'weekday') || ')' ||
        ' via ' || platform || ', place of listening code ' || where_listened_code AS phrase
FROM FACT_LISTENING;


-- DIM_RESPONDENT: every distinct demographic combination -----------------------------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT 'DIM_RESPONDENT', 'combination', 'Respondents: ' || phrase, filters, COUNT(*)
FROM RESPONDENT_PHRASE GROUP BY phrase, filters;

-- FACT_LISTENING: every respondent combination x station name they listen to ---------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT 'FACT_LISTENING', 'profile',
       'Listeners who are ' || rp.phrase || ', listening to ' || s.station_name,
       OBJECT_INSERT(rp.filters, 'DIM_STATION.STATION_NAME', s.station_name),
       COUNT(*)
FROM FACT_LISTENING f
JOIN RESPONDENT_PHRASE rp USING (respondent_id)
JOIN DIM_STATION s USING (station_code)
GROUP BY rp.phrase, rp.filters, s.station_name;

-- FACT_LISTENING and FACT_BRAND_LISTENING: when / how combinations -------------------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT t.table_name, 'combination', lp.phrase,
       OBJECT_CONSTRUCT(t.table_name || '.DAY_NAME', lp.day_name,
                        t.table_name || '.DAY_BAND', lp.day_band,
                        t.table_name || '.IS_WEEKEND', lp.is_weekend,
                        t.table_name || '.PLATFORM', lp.platform,
                        t.table_name || '.WHERE_LISTENED_CODE', lp.where_listened_code),
       NULL
FROM LISTENING_PHRASE lp
CROSS JOIN (SELECT 'FACT_LISTENING' AS table_name UNION ALL SELECT 'FACT_BRAND_LISTENING') t;

-- FACT_BRAND_LISTENING: brand x platform --------------------------------------------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT 'FACT_BRAND_LISTENING', 'combination',
       'Listening to ' || b.brand_name || ' via ' || f.platform,
       OBJECT_CONSTRUCT('DIM_BRAND.BRAND_NAME', b.brand_name,
                        'FACT_BRAND_LISTENING.PLATFORM', f.platform),
       COUNT(*)
FROM FACT_BRAND_LISTENING f JOIN DIM_BRAND b USING (brand_id)
GROUP BY b.brand_name, f.platform;

-- FACT_BRAND_LISTENING: brand x platform x day band ----------------------------------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT 'FACT_BRAND_LISTENING', 'combination',
       'Listening to ' || b.brand_name || ' via ' || f.platform || ' on ' || f.day_band,
       OBJECT_CONSTRUCT('DIM_BRAND.BRAND_NAME', b.brand_name,
                        'FACT_BRAND_LISTENING.PLATFORM', f.platform,
                        'FACT_BRAND_LISTENING.DAY_BAND', f.day_band),
       COUNT(*)
FROM FACT_BRAND_LISTENING f JOIN DIM_BRAND b USING (brand_id)
GROUP BY b.brand_name, f.platform, f.day_band;

-- DIM_STATION: every station code (station x platform) --------------------------------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT 'DIM_STATION', 'combination',
       'Station ' || station_name || ' on ' || platform ||
       ', ' || CASE WHEN is_bbc_local_regional THEN 'BBC local/regional station'
                    WHEN is_bbc THEN 'BBC station'
                    WHEN is_national_commercial THEN 'national commercial station'
                    WHEN is_local_commercial THEN 'local commercial station'
                    WHEN is_commercial THEN 'commercial station'
                    ELSE 'other station' END ||
       COALESCE(', genre code ' || genre, '') ||
       COALESCE(', broadcasting in ' || NULLIF(ARRAY_TO_STRING(ARRAY_CONSTRUCT_COMPACT(
            IFF(region_london, 'London', NULL), IFF(region_midlands, 'Midlands', NULL),
            IFF(region_north_west, 'North West', NULL), IFF(region_yorkshire, 'Yorkshire', NULL),
            IFF(region_north_east, 'North East', NULL), IFF(region_central_scotland, 'Central Scotland', NULL),
            IFF(region_north_scotland, 'North Scotland', NULL), IFF(region_south, 'South', NULL),
            IFF(region_east_of_england, 'East of England', NULL), IFF(region_south_west, 'South West', NULL),
            IFF(region_ulster, 'Ulster', NULL), IFF(region_border, 'Border', NULL), IFF(region_west, 'West', NULL),
            IFF(region_wales, 'Wales', NULL), IFF(region_channel_islands, 'Channel Islands', NULL)), ', '), ''), '') ||
       ' (station code ' || station_code || ')',
       OBJECT_CONSTRUCT('DIM_STATION.STATION_CODE', station_code,
                        'DIM_STATION.STATION_NAME', station_name,
                        'DIM_STATION.PLATFORM', platform),
       1
FROM DIM_STATION;

-- DIM_BRAND: every brand ----------------------------------------------------------------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT 'DIM_BRAND', 'combination',
       'Brand ' || brand_name ||
       ', owned by ' || IFF(owner = 'UNKNOWN', 'an unknown owner', owner) ||
       CASE WHEN is_national THEN ', national' WHEN is_local THEN ', local' ELSE '' END ||
       CASE WHEN is_commercial THEN ' commercial' WHEN is_commercial = FALSE THEN ' non-commercial' ELSE '' END ||
       CASE WHEN report_is_brand THEN ' brand total' WHEN report_is_network THEN ' network'
            WHEN report_is_region THEN ' regional grouping' WHEN report_is_station THEN ' station' ELSE '' END ||
       IFF(is_airtime_package, ', airtime trading package', '') ||
       IFF(is_sponsorship_package, ', sponsorship trading package', '') ||
       IFF(is_traded, ', traded', ', not traded') ||
       IFF(rajar_report_number IS NULL, ', no matching RAJAR report',
           ', matched to RAJAR report ' || rajar_report_name || ' (' || LOWER(rajar_match_type) || ')' ||
           COALESCE(', published survey period ' || published_survey_period, '')),
       OBJECT_CONSTRUCT('DIM_BRAND.BRAND_ID', brand_id, 'DIM_BRAND.BRAND_NAME', brand_name,
                        'DIM_BRAND.OWNER', owner),
       1
FROM DIM_BRAND;

-- BRIDGE_BRAND_STATION: brand membership ---------------------------------------------------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT 'BRIDGE_BRAND_STATION', 'combination',
       'Brand ' || b.brand_name || ' includes station ' ||
       COALESCE(s.station_name || ' on ' || s.platform || ' (station code ' || bs.station_code || ')',
                'code ' || bs.station_code || ' (not in the station list)'),
       OBJECT_CONSTRUCT('BRIDGE_BRAND_STATION.BRAND_ID', bs.brand_id,
                        'BRIDGE_BRAND_STATION.STATION_CODE', bs.station_code),
       1
FROM BRIDGE_BRAND_STATION bs
JOIN DIM_BRAND b USING (brand_id)
LEFT JOIN DIM_STATION s USING (station_code);


-- Single values: one row per column value -----------------------------------------------
INSERT INTO SCHEMA_VECTOR_TEXT
SELECT table_name, 'single_value', context, OBJECT_CONSTRUCT(col, val), source_rows FROM (
    SELECT 'DIM_RESPONDENT' table_name, 'DIM_RESPONDENT.GENDER' col, gender::VARIANT val, gender || ' (gender)' context, COUNT(*) source_rows FROM DIM_RESPONDENT GROUP BY gender
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.AGE_BAND', age_band::VARIANT,
                     'People aged ' || age_band || ' (age band' || DECODE(age_band,
                         'Under 15', ': children',
                         '15-24', ': young people, youth, teenagers and students',
                         '25-34', ': young adults',
                         '35-44', ': middle-aged adults',
                         '45-54', ': middle-aged adults',
                         '55-64', ': older adults',
                         '65+', ': older people, pensioners, retired', '') || ')', COUNT(*) FROM DIM_RESPONDENT GROUP BY age_band
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.SOCIAL_GRADE', social_grade::VARIANT, 'Social grade ' || social_grade, COUNT(*) FROM DIM_RESPONDENT GROUP BY social_grade
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.SOCIAL_SEGMENT', social_segment::VARIANT,
                     IFF(social_segment = 'ABC1',
                         'Middle class, white collar, upmarket people: ABC1 (social grades A, B, C1)',
                         'Working class, blue collar, downmarket people: C2DE (social grades C2, D, E)'), COUNT(*) FROM DIM_RESPONDENT GROUP BY social_segment
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.ILR_REGION', ilr_region::VARIANT, 'People living in ' || ilr_region || ' (region)', COUNT(*) FROM DIM_RESPONDENT GROUP BY ilr_region
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.HAS_CHILDREN_0_14', has_children_0_14::VARIANT,
                     IFF(has_children_0_14, 'Parents with children aged 0-14', 'People without children aged 0-14'), COUNT(*) FROM DIM_RESPONDENT GROUP BY has_children_0_14
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.HOUSEHOLD_SIZE', household_size::VARIANT,
                     'Household of ' || household_size || IFF(household_size >= 5, ' or more', '') || IFF(household_size = 1, ' person', ' people'), COUNT(*) FROM DIM_RESPONDENT GROUP BY household_size
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.IS_ADULT_15_PLUS', is_adult_15_plus::VARIANT,
                     IFF(is_adult_15_plus, 'Adults aged 15 and over', 'Children under 15'), COUNT(*) FROM DIM_RESPONDENT GROUP BY is_adult_15_plus
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_GLOBAL_PLAYER', TRUE::VARIANT, 'Uses the Global Player app', COUNT_IF(uses_global_player) FROM DIM_RESPONDENT
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_BBC_SOUNDS', TRUE::VARIANT, 'Uses the BBC Sounds app', COUNT_IF(uses_bbc_sounds) FROM DIM_RESPONDENT
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_RADIOPLAYER', TRUE::VARIANT, 'Uses the Radioplayer app', COUNT_IF(uses_radioplayer) FROM DIM_RESPONDENT
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_CAPITAL_APP', TRUE::VARIANT, 'Uses the Capital app', COUNT_IF(uses_capital_app) FROM DIM_RESPONDENT
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_HEART_APP', TRUE::VARIANT, 'Uses the Heart app', COUNT_IF(uses_heart_app) FROM DIM_RESPONDENT
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_KISS_APP', TRUE::VARIANT, 'Uses the Kiss app', COUNT_IF(uses_kiss_app) FROM DIM_RESPONDENT
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_MAGIC_APP', TRUE::VARIANT, 'Uses the Magic app', COUNT_IF(uses_magic_app) FROM DIM_RESPONDENT
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_ABSOLUTE_RADIO_APP', TRUE::VARIANT, 'Uses the Absolute Radio app', COUNT_IF(uses_absolute_radio_app) FROM DIM_RESPONDENT
    UNION ALL SELECT 'DIM_RESPONDENT', 'DIM_RESPONDENT.USES_TALKSPORT_APP', TRUE::VARIANT, 'Uses the talkSPORT app', COUNT_IF(uses_talksport_app) FROM DIM_RESPONDENT

    UNION ALL SELECT 'FACT_LISTENING', 'FACT_LISTENING.PLATFORM', platform::VARIANT, 'Listening via ' || platform || ' (platform)', COUNT(*) FROM FACT_LISTENING GROUP BY platform
    UNION ALL SELECT 'FACT_LISTENING', 'FACT_LISTENING.DAY_NAME', day_name::VARIANT, 'Listening on ' || day_name, COUNT(*) FROM FACT_LISTENING GROUP BY day_name
    UNION ALL SELECT 'FACT_LISTENING', 'FACT_LISTENING.DAY_BAND', day_band::VARIANT, 'Listening on ' || day_band || ' (day band)', COUNT(*) FROM FACT_LISTENING GROUP BY day_band
    UNION ALL SELECT 'FACT_LISTENING', 'FACT_LISTENING.IS_WEEKEND', is_weekend::VARIANT, IFF(is_weekend, 'Weekend listening', 'Weekday listening'), COUNT(*) FROM FACT_LISTENING GROUP BY is_weekend
    UNION ALL SELECT 'FACT_LISTENING', 'FACT_LISTENING.WHERE_LISTENED_CODE', where_listened_code::VARIANT, 'Place of listening code ' || where_listened_code, COUNT(*) FROM FACT_LISTENING GROUP BY where_listened_code

    UNION ALL SELECT 'FACT_BRAND_LISTENING', 'FACT_BRAND_LISTENING.PLATFORM', platform::VARIANT, 'Brand listening via ' || platform || ' (platform)', COUNT(*) FROM FACT_BRAND_LISTENING GROUP BY platform
    UNION ALL SELECT 'FACT_BRAND_LISTENING', 'FACT_BRAND_LISTENING.DAY_NAME', day_name::VARIANT, 'Brand listening on ' || day_name, COUNT(*) FROM FACT_BRAND_LISTENING GROUP BY day_name
    UNION ALL SELECT 'FACT_BRAND_LISTENING', 'FACT_BRAND_LISTENING.DAY_BAND', day_band::VARIANT, 'Brand listening on ' || day_band || ' (day band)', COUNT(*) FROM FACT_BRAND_LISTENING GROUP BY day_band
    UNION ALL SELECT 'FACT_BRAND_LISTENING', 'FACT_BRAND_LISTENING.IS_WEEKEND', is_weekend::VARIANT, IFF(is_weekend, 'Weekend brand listening', 'Weekday brand listening'), COUNT(*) FROM FACT_BRAND_LISTENING GROUP BY is_weekend

    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.STATION_NAME', station_name::VARIANT, 'Station ' || station_name || ' (all platforms)', COUNT(*) FROM DIM_STATION GROUP BY station_name
    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.PLATFORM', platform::VARIANT, 'Stations on ' || platform || ' (platform)', COUNT(*) FROM DIM_STATION GROUP BY platform
    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.GENRE', genre::VARIANT, 'Stations with genre code ' || genre, COUNT(*) FROM DIM_STATION WHERE genre IS NOT NULL GROUP BY genre
    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.IS_BBC', TRUE::VARIANT, 'BBC stations', COUNT_IF(is_bbc) FROM DIM_STATION
    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.IS_COMMERCIAL', TRUE::VARIANT, 'Commercial radio stations', COUNT_IF(is_commercial) FROM DIM_STATION
    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.IS_NATIONAL_COMMERCIAL', TRUE::VARIANT, 'National commercial radio stations', COUNT_IF(is_national_commercial) FROM DIM_STATION
    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.IS_LOCAL_COMMERCIAL', TRUE::VARIANT, 'Local commercial radio stations', COUNT_IF(is_local_commercial) FROM DIM_STATION
    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.IS_BBC_LOCAL_REGIONAL', TRUE::VARIANT, 'BBC local and regional stations', COUNT_IF(is_bbc_local_regional) FROM DIM_STATION
    UNION ALL SELECT 'DIM_STATION', 'DIM_STATION.REGION_' || UPPER(REPLACE(r.name, ' ', '_')), TRUE::VARIANT, 'Stations broadcasting in ' || r.name, NULL
              FROM (SELECT column1 AS name FROM VALUES ('London'), ('Midlands'), ('North West'), ('Yorkshire'), ('North East'),
                    ('Central Scotland'), ('North Scotland'), ('South'), ('East of England'), ('South West'), ('Ulster'),
                    ('Border'), ('West'), ('Wales'), ('Channel Islands')) r

    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.OWNER', owner::VARIANT, 'Brands owned by ' || owner, COUNT(*) FROM DIM_BRAND GROUP BY owner
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.RAJAR_MATCH_TYPE', rajar_match_type::VARIANT, 'Brands whose RAJAR match is: ' || rajar_match_type, COUNT(*) FROM DIM_BRAND GROUP BY rajar_match_type
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.PUBLISHED_SURVEY_PERIOD', published_survey_period::VARIANT,
                     'Brands published on a ' || DECODE(published_survey_period, 'Q', 'quarterly (3-month)', 'H', 'half-year (6-month)', 'Y', 'annual (12-month)') || ' RAJAR survey period', COUNT(*)
              FROM DIM_BRAND WHERE published_survey_period IS NOT NULL GROUP BY published_survey_period
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.IS_NATIONAL', TRUE::VARIANT, 'National brands', COUNT_IF(is_national) FROM DIM_BRAND
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.IS_LOCAL', TRUE::VARIANT, 'Local brands', COUNT_IF(is_local) FROM DIM_BRAND
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.IS_COMMERCIAL', TRUE::VARIANT, 'Commercial brands', COUNT_IF(is_commercial) FROM DIM_BRAND
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.IS_AIRTIME_PACKAGE', TRUE::VARIANT, 'Airtime trading packages', COUNT_IF(is_airtime_package) FROM DIM_BRAND
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.IS_SPONSORSHIP_PACKAGE', TRUE::VARIANT, 'Sponsorship trading packages', COUNT_IF(is_sponsorship_package) FROM DIM_BRAND
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.IS_TRADED', TRUE::VARIANT, 'Traded brands', COUNT_IF(is_traded) FROM DIM_BRAND
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.REPORT_IS_BRAND', TRUE::VARIANT, 'Brand totals (whole brand across regions)', COUNT_IF(report_is_brand) FROM DIM_BRAND
    UNION ALL SELECT 'DIM_BRAND', 'DIM_BRAND.REPORT_IS_NETWORK', TRUE::VARIANT, 'Radio networks', COUNT_IF(report_is_network) FROM DIM_BRAND
);


-- -------------------------------------------------------------------------------------
-- Stage 2: embed and persist
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE SCHEMA_VECTORS (
    VECTOR_ID    NUMBER        COMMENT 'Surrogate key.',
    TABLE_NAME   STRING        COMMENT 'ANALYTICS table the entry describes and should be queried.',
    ENTRY_TYPE   STRING        COMMENT 'combination | profile (respondent x station) | single_value',
    CONTEXT      STRING        COMMENT 'English sentence built from the categorical values.',
    VECTOR       VECTOR(FLOAT, 768) COMMENT 'snowflake-arctic-embed-m-v1.5 embedding of CONTEXT.',
    FILTERS      OBJECT        COMMENT 'Column/value filters; keys are TABLE.COLUMN.',
    FILTER_SQL   STRING        COMMENT 'FILTERS as a SQL WHERE fragment (AND-joined).',
    SOURCE_ROWS  NUMBER        COMMENT 'Rows in the source table matching the filters (null when not computed).',
    EMBED_MODEL  STRING        COMMENT 'Embedding model used.'
)
COMMENT = 'Vector store of categorical value combinations for every ANALYTICS table. Embed a question with the same model and rank by VECTOR_COSINE_SIMILARITY to find filters.';

INSERT INTO SCHEMA_VECTORS
SELECT ROW_NUMBER() OVER (ORDER BY TABLE_NAME, ENTRY_TYPE, CONTEXT),
       TABLE_NAME, ENTRY_TYPE, CONTEXT,
       SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m-v1.5', CONTEXT),
       FILTERS, FILTERS_TO_SQL(FILTERS), SOURCE_ROWS,
       'snowflake-arctic-embed-m-v1.5'
FROM SCHEMA_VECTOR_TEXT;


-- -------------------------------------------------------------------------------------
-- Search function: top-k entries for a question, optionally restricted to one table.
-- The question gets the Arctic retrieval prefix; stored contexts are embedded without it.
--   SELECT * FROM TABLE(SEARCH_SCHEMA_VECTORS('young women in London on DAB'));
--   SELECT * FROM TABLE(SEARCH_SCHEMA_VECTORS('Global national brands', 'DIM_BRAND', 5));
--   SELECT * FROM TABLE(SEARCH_SCHEMA_VECTORS('upmarket listeners', '', 5, 'single_value'));
-- Pass '' (not a bare NULL) to skip a filter.
-- -------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS SEARCH_SCHEMA_VECTORS(STRING, STRING, NUMBER);
CREATE OR REPLACE FUNCTION SEARCH_SCHEMA_VECTORS(QUESTION STRING, TABLE_FILTER STRING DEFAULT NULL, K NUMBER DEFAULT 10,
                                                 ENTRY_FILTER STRING DEFAULT NULL)
RETURNS TABLE (TABLE_NAME STRING, ENTRY_TYPE STRING, CONTEXT STRING, FILTERS OBJECT, FILTER_SQL STRING,
               SOURCE_ROWS NUMBER, SIMILARITY FLOAT)
COMMENT = 'Semantic search over SCHEMA_VECTORS. Empty TABLE_FILTER / ENTRY_FILTER (combination, profile, single_value) means all; K defaults to 10.'
AS $$
    SELECT TABLE_NAME, ENTRY_TYPE, CONTEXT, FILTERS, FILTER_SQL, SOURCE_ROWS,
           VECTOR_COSINE_SIMILARITY(VECTOR,
               SNOWFLAKE.CORTEX.EMBED_TEXT_768('snowflake-arctic-embed-m-v1.5',
                   'Represent this sentence for searching relevant passages: ' || QUESTION)) AS SIMILARITY
    FROM HACKATHON_TEAM_GINGER_DB.ANALYTICS.SCHEMA_VECTORS
    WHERE (COALESCE(TABLE_FILTER, '') = '' OR TABLE_NAME = UPPER(TABLE_FILTER))
      AND (COALESCE(ENTRY_FILTER, '') = '' OR ENTRY_TYPE = LOWER(ENTRY_FILTER))
    QUALIFY ROW_NUMBER() OVER (ORDER BY SIMILARITY DESC) <= K
$$;
