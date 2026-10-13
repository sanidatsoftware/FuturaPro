-- Ruolo dell'applicazione: NON superuser e senza BYPASSRLS, altrimenti la
-- Row-Level Security non lo vincolerebbe. CREATEDB serve solo ai test.
CREATE ROLE futurapro LOGIN PASSWORD 'futurapro' CREATEDB;
CREATE DATABASE futurapro OWNER futurapro;
