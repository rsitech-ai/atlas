CREATE OR REPLACE FUNCTION atlas_core.reject_artifact_content_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'artifact content metadata is immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER artifact_contents_are_immutable
BEFORE UPDATE OR DELETE ON atlas_core.artifact_contents
FOR EACH ROW
EXECUTE FUNCTION atlas_core.reject_artifact_content_mutation();

CREATE TRIGGER artifact_contents_reject_truncate
BEFORE TRUNCATE ON atlas_core.artifact_contents
FOR EACH STATEMENT
EXECUTE FUNCTION atlas_core.reject_artifact_content_mutation();
