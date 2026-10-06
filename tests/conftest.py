LOCATION = "test_ebsconet_location (TEST-EBSCONET-LOC)"


def with_test_values(cfg):
    """The seed ebsconet_config.json leaves funds, location and material type blank; tests
    that check the fall-back to the config defaults need values."""
    cfg["fund_by_route"] = {"online": "TEST-ELEC", "print": "TEST-PRINT", "pe": "TEST-PRINT"}
    cfg["folio"]["location"] = LOCATION
    cfg["folio"]["physical_material_type"] = "journal"
    cfg["expense_class_by_subject"] = {"Physical Sciences": "PHY", "Social Sciences": "SOC"}
    cfg["default_expense_class"] = "GEN"
    cfg["customer_choices"] = {"location": [LOCATION], "material_type": ["journal"]}
    return cfg
