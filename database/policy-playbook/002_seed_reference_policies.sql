-- Synthetic reference policies for the lab. They are illustrative, not real operating rules.
-- Change them with a new migration; never edit this file after it is applied.

INSERT INTO policy.policies (policy_id, version, title, status, content) VALUES
('policy_remote_action', '1.0', 'Synthetic Remote Action Policy', 'active',
 'Remote vehicle commands require an active telematics unit that is eligible for remote commands. '
 'Any remote command needs approval from a safety officer. Commands are never sent to a vehicle '
 'reporting a collision until it has been inspected.'),
('policy_customer_comms', '1.0', 'Synthetic Customer Communication Policy', 'active',
 'Messages to a fleet manager require approval from an operations manager and must reference the '
 'approval. Direct messages to end customers are not permitted from the control lab.'),
('policy_case_handling', '1.0', 'Synthetic Case Handling Policy', 'active',
 'Service cases may be opened automatically for evidence-backed issues up to medium risk. '
 'Higher-risk cases need an operations manager. Internal team notifications are always permitted.'),
('policy_escalation', '1.0', 'Synthetic Escalation Policy', 'active',
 'Critical safety events go to safety operations within 15 minutes. Battery and diagnostic warnings '
 'go to fleet operations within 4 hours. Connectivity issues go to the telematics support team.')
ON CONFLICT DO NOTHING;

INSERT INTO policy.playbooks (playbook_id, version, title, event_types, status, body) VALUES
('pb_battery_voltage', '1.0', 'Battery Voltage Triage', '{battery_voltage}', 'active',
 'Confirm the low voltage reading persists across at least two samples. Check for recent missed '
 'heartbeats and diagnostic failures, which suggest the battery is failing rather than discharged. '
 'Open a service case for a battery inspection and notify fleet operations. If voltage is below '
 '11.0 V, recommend the vehicle is not dispatched until inspected.'),
('pb_connectivity_loss', '1.0', 'Connectivity Loss Triage', '{heartbeat_missed,connectivity_lost}', 'active',
 'Check whether other vehicles in the same region lost connectivity at the same time, which points '
 'to a network outage. For a single vehicle, check battery voltage and the telematics unit firmware. '
 'Escalate to telematics support if the unit stays offline for more than one hour.'),
('pb_diagnostic_failure', '1.0', 'Diagnostic Trouble Code Triage', '{diagnostic_failure}', 'active',
 'Look up the diagnostic trouble code and the vehicle maintenance history for repeated failures. '
 'Critical codes require a service case and an inspection before the next dispatch. Warning codes '
 'can be scheduled with the preferred service provider.'),
('pb_collision', '1.0', 'Collision Response', '{collision_detected}', 'active',
 'Treat every collision event as critical. Notify safety operations immediately, open a service case, '
 'and block remote commands to the vehicle until an inspection is recorded.'),
('pb_firmware_failure', '1.0', 'Firmware Update Failure', '{firmware_update_failed}', 'active',
 'Check whether the failure affects other units on the same hardware model and firmware version. '
 'Retry once during the next ignition-off window, then escalate to telematics support.')
ON CONFLICT DO NOTHING;

INSERT INTO policy.escalation_rules
    (rule_id, event_type, severity, target_team, response_target_minutes, policy_id) VALUES
('rule_collision_critical', 'collision_detected', 'critical', 'safety_ops', 15, 'policy_escalation'),
('rule_battery_critical', 'battery_voltage', 'critical', 'safety_ops', 30, 'policy_escalation'),
('rule_battery_warning', 'battery_voltage', 'warning', 'fleet_ops', 240, 'policy_escalation'),
('rule_diagnostic_critical', 'diagnostic_failure', 'critical', 'safety_ops', 30, 'policy_escalation'),
('rule_diagnostic_warning', 'diagnostic_failure', 'warning', 'fleet_ops', 240, 'policy_escalation'),
('rule_heartbeat_warning', 'heartbeat_missed', 'warning', 'telematics_support', 120, 'policy_escalation'),
('rule_connectivity_warning', 'connectivity_lost', 'warning', 'telematics_support', 120, 'policy_escalation'),
('rule_firmware_warning', 'firmware_update_failed', 'warning', 'telematics_support', 480, 'policy_escalation'),
('rule_any_critical', '*', 'critical', 'operations_duty_manager', 30, 'policy_escalation')
ON CONFLICT DO NOTHING;

INSERT INTO policy.action_controls
    (action_type, approval_mode, max_autonomous_risk, required_reviewer_role, policy_id, policy_version) VALUES
('internal_notification', 'none', 'critical', NULL, 'policy_case_handling', '1.0'),
('create_service_case', 'required', 'medium', 'operations_manager', 'policy_case_handling', '1.0'),
('schedule_maintenance', 'required', 'low', 'operations_manager', 'policy_case_handling', '1.0'),
('fleet_notification', 'required', NULL, 'operations_manager', 'policy_customer_comms', '1.0'),
('remote_command', 'required', NULL, 'safety_officer', 'policy_remote_action', '1.0'),
('customer_notification', 'blocked', NULL, NULL, 'policy_customer_comms', '1.0')
ON CONFLICT DO NOTHING;
