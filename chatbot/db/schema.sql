-- Reporting database schema for the Analytics 7 chatbot demo.
-- Tables mirror the CIS tables the in-scope Cube YAMLs read, so each cube's
-- own SQL runs unchanged. Only the columns those cubes use are present.

CREATE TABLE pu_account (
    account_no      varchar(12) NOT NULL,
    occupant_code   varchar(4)  NOT NULL,
    name            varchar(80) NOT NULL,
    debtor_no       varchar(12),
    serv_street_no  varchar(10),
    serv_street_mod varchar(10),
    serv_street     varchar(60),
    serv_city       varchar(40),
    serv_province   varchar(4),
    serv_postal_zip char(10),
    -- Not read by any Cube YAML; added for the chatbot overlay (customer class).
    -- The real CIS column name is still to be confirmed.
    cust_class      varchar(4),
    PRIMARY KEY (account_no, occupant_code)
);

CREATE TABLE pu_account_pay (
    account_no         varchar(12) NOT NULL,
    occupant_code      varchar(4)  NOT NULL,
    utility_type       varchar(2)  NOT NULL,
    start_date         date,
    end_date           date,
    due_date           date,
    last_bill_amount   numeric(12,2),
    current_balance    numeric(12,2),
    overdue_balance    numeric(12,2),
    latecharge_balance numeric(12,2),
    interest_balance   numeric(12,2)
);

CREATE TABLE icphdrh (
    login   varchar(20) PRIMARY KEY,
    batchid varchar(20) NOT NULL,
    userid  varchar(20) NOT NULL
);

CREATE TABLE icpcashm (
    login        varchar(20) NOT NULL REFERENCES icphdrh(login),
    entry_no     varchar(20) NOT NULL,
    trans_date   timestamp   NOT NULL,
    tendered_amt numeric(12,2) NOT NULL
);

CREATE TABLE pu_ar_descript (
    ar_code     varchar(6) PRIMARY KEY,
    ar_descript varchar(60) NOT NULL
);

CREATE TABLE glsvdata (
    jrnl_no     varchar(12) PRIMARY KEY,
    applcode    varchar(4) NOT NULL,
    journalcode varchar(4) NOT NULL
);

CREATE TABLE pu_balance_hist (
    sequence_     integer PRIMARY KEY,
    account_no    varchar(12) NOT NULL,
    occupant_code varchar(4)  NOT NULL,
    run_date      date NOT NULL,
    trans_date    date NOT NULL,
    jour_code     varchar(4) NOT NULL,
    jour_no       varchar(12) NOT NULL,
    trans_amt     numeric(12,2) NOT NULL,
    desc_code     varchar(6) NOT NULL
);

CREATE TABLE csrctypr (
    calltype    varchar(10) NOT NULL,
    callcode    varchar(10) NOT NULL,
    description varchar(60),
    shortdesc   varchar(30),
    PRIMARY KEY (calltype, callcode)
);

CREATE TABLE csrstatc (
    callstatus varchar(4) PRIMARY KEY,
    shortdesc  varchar(30)
);

CREATE TABLE csrcalld (
    call_number   varchar(12) PRIMARY KEY,
    createdon     timestamp NOT NULL,
    calltype      varchar(10) NOT NULL,
    callcode      varchar(10) NOT NULL,
    order_no      varchar(12),
    ordercode     varchar(10),
    createdby     varchar(20) NOT NULL,
    account_no    varchar(12),
    occupant_code varchar(4),
    scheduledon   timestamp,
    completedon   timestamp,
    callstatus    varchar(4)
);
