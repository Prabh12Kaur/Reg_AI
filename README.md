To install dependencies use:
pip install -r requirements.txt

To run:
python run.py

Before using token_api, make sure patient_tokens table is there in your database:

CREATE TABLE patient_tokens (
    token UUID PRIMARY KEY,
    id INTEGER NOT NULL, -- daily ID (resets every day)
    patient_id VARCHAR(50) NOT NULL,
    department_id VARCHAR(50) NOT NULL,
    datetime TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'waiting', -- new: token lifecycle status
    status_updated_at TIMESTAMP DEFAULT NOW() -- new: timestamp of last status change
);

Make sure the current_token table is installed in your system before using announcement_api:

CREATE TABLE current_token (
    id SERIAL PRIMARY KEY,
    token_uuid UUID NOT NULL,
    token_number INTEGER NOT NULL,
    patient_id VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE current_token ADD COLUMN department_id VARCHAR(50);

OR

CREATE TABLE current_token (
    id SERIAL PRIMARY KEY,
    token_uuid UUID NOT NULL,
    token_number INTEGER NOT NULL,
    patient_id VARCHAR(255) NOT NULL,
    department_id VARCHAR(50) NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    
    CONSTRAINT unique_department UNIQUE (department_id)
);
