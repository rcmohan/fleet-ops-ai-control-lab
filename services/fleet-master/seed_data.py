FLEETS = {
    "flt_demo_001": {
        "fleetId": "flt_demo_001",
        "customerName": "Northstar Synthetic Logistics",
        "industryCode": "logistics",
        "declaredFleetSize": 100,
        "contractTier": "enterprise",
        "slaLevel": "mission_critical",
        "priorityLevel": "high",
        "preferredServiceProviderId": "sp_demo_001",
        "lifecycleStatus": "active",
        "operatingRegions": ["us-east", "us-central"],
        "escalationContacts": [
            {
                "contactId": "contact_demo_001",
                "name": "Demo Reviewer",
                "role": "fleet_manager",
                "email": "reviewer@example.invalid",
                "phone": None,
                "escalationRank": 1,
                "active": True,
            }
        ],
        "sourceVersion": 1,
    }
}
