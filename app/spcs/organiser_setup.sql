-- =====================================================================================
-- For the hackathon organisers (Josie / Samy): lets Team Ginger's RAJAR Pulse service
-- call the OpenAI API. Needs ACCOUNTADMIN because it creates an integration.
--
-- Team Ginger has already created (via app/spcs/deploy.py):
--   HACKATHON_TEAM_GINGER_DB.ANALYTICS.OPENAI_EGRESS   network rule: api.openai.com:443 only
--   HACKATHON_TEAM_GINGER_DB.ANALYTICS.OPENAI_API_KEY  secret holding the team's own OpenAI key
-- =====================================================================================

USE ROLE ACCOUNTADMIN;

CREATE EXTERNAL ACCESS INTEGRATION IF NOT EXISTS PULSE_OPENAI_EAI
  ALLOWED_NETWORK_RULES = (HACKATHON_TEAM_GINGER_DB.ANALYTICS.OPENAI_EGRESS)
  ALLOWED_AUTHENTICATION_SECRETS = (HACKATHON_TEAM_GINGER_DB.ANALYTICS.OPENAI_API_KEY)
  ENABLED = TRUE
  COMMENT = 'Team Ginger RAJAR Pulse: outbound HTTPS to api.openai.com only';

GRANT USAGE ON INTEGRATION PULSE_OPENAI_EAI TO ROLE HACKATHON_TEAM_GINGER;

-- Then Team Ginger runs:  python app/spcs/deploy.py --eai PULSE_OPENAI_EAI
-- (or: ALTER SERVICE HACKATHON_TEAM_GINGER_DB.ANALYTICS.RAJAR_PULSE SET EXTERNAL_ACCESS_INTEGRATIONS = (PULSE_OPENAI_EAI);)
