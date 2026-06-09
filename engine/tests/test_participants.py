import pytest
from scratch.compile_participants import (
    clean_email, clean_phone, normalize_name, split_full_name,
    clean_and_swap_city_org, is_company_or_org, clean_activity_name
)

def test_clean_email():
    assert clean_email("TEST@GMAIL.COM") == "test@gmail.com"
    assert clean_email("test+label@gmail.com") == "test@gmail.com"
    assert clean_email("test.email@gmail.com") == "testemail@gmail.com"
    assert clean_email("mailto:info@lascuolaopensource.xyz") == "info@lascuolaopensource.xyz"
    assert clean_email("<info@lascuolaopensource.xyz>") == "info@lascuolaopensource.xyz"
    assert clean_email("invalid_email") == ""

def test_clean_phone():
    assert clean_phone("+39 333 123 4567") == "+393331234567"
    assert clean_phone("333 123 4567") == "+393331234567"
    assert clean_phone("00393331234567") == "+393331234567"
    assert clean_phone("333-123.4567") == "+393331234567"
    assert clean_phone("invalid") == ""

def test_normalize_name():
    # Heuristic for ALL CAPS (COGNOME NOME)
    assert normalize_name("ROSSI MARIO") == ("Mario", "Rossi")
    # Standard Title Case (Nome Cognome)
    assert normalize_name("Mario Rossi") == ("Mario", "Rossi")
    assert normalize_name("mario rossi") == ("Mario", "Rossi")
    assert normalize_name("Mario") == ("Mario", "")

def test_split_full_name():
    assert split_full_name("Mario Rossi") == ("Mario", "Rossi")
    assert split_full_name("ROSSI MARIO") == ("Mario", "Rossi")

def test_is_company_or_org():
    # True for companies
    assert is_company_or_org("Zoom Video", "Communications, Inc.", "") is True
    assert is_company_or_org("Flixbus", "", "") is True
    assert is_company_or_org("", "", "no-reply@zoom.us") is True
    assert is_company_or_org("", "", "info@company.com") is True
    
    # False for real people
    assert is_company_or_org("Mario", "Rossi", "mario.rossi@gmail.com") is False
    assert is_company_or_org("John", "Doe", "jdoe@lascuolaopensource.xyz") is False

def test_clean_and_swap_city_org():
    # Misplaced city in organization, swapped with organization
    assert clean_swap_helper("CNR", "Bari") == ("Bari", "CNR")
    assert clean_swap_helper("", "Bari") == ("Bari", "")
    
    # Misplaced organization in city
    assert clean_swap_helper("S.r.l.", "") == ("", "S.R.L.")
    assert clean_swap_helper("CNR", "") == ("", "CNR")
    
    # Correct arrangement
    assert clean_swap_helper("Bari", "CNR") == ("Bari", "CNR")
    
    # Placeholders cleaned
    assert clean_swap_helper("nan", "none") == ("", "")
    assert clean_swap_helper("Bari (BA)", "-") == ("Bari (BA)", "")

def clean_swap_helper(city, org):
    return clean_and_swap_city_org(city, org)

def test_clean_activity_name():
    assert clean_activity_name("paypal 2024.CSV", "") == "Donazione / Pagamento SOS"
    assert clean_activity_name("189950_Iscritti Mef marzo 2026.xlsx", "") == "Corso MEF (Ministero Economia e Finanze)"
    assert clean_activity_name("189951_USB__0326.xlsx", "") == "Corso USB (Unione Sindacale di Base)"
    assert clean_activity_name("0_iscrizioni_1617.csv", "") == "Iscrizioni Corsi 2016-2017"
    assert clean_activity_name("attachment", "189950_Iscritti Mef marzo 2026.xlsx") == "Corso MEF (Ministero Economia e Finanze)"
    assert clean_activity_name("Corso Pippo", "") == "Corso Pippo"

