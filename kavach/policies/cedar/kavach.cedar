// KAVACH's rules in Cedar (E4). KAVACH's engines compute the facts (provenance of each argument, what the action
// does, staged rows, lookalike domains...) into the request context; these policies decide.
//
// Two actions per tool call:
//   Action::"execute"       may this call happen at all?          forbid = DENY
//   Action::"auto_execute"  may it happen without a person?       forbid = needs approval (a floor; model can't lift)
// A rule that blocks also forbids auto_execute (anything not allowed at all is not allowed automatically either).
// Every policy carries the rule id that receipts cite.

permit(principal, action, resource);

// ---------------------------------------------------------------- blocking rules (DENY)
@id("KILL")
forbid(principal, action, resource) when { context.killed };

@id("R6")
forbid(principal, action, resource) when { !context.known_tool || context.pin_mismatch };

@id("R7")
forbid(principal, action, resource) when { context.schema_error || context.read_tool_writes || context.stage_error };

@id("R8")
forbid(principal, action, resource) when { !context.role_allowed };

@id("R1")
forbid(principal, action, resource) when { context.external && !context.ingress && context.untrusted_control };

@id("R11")
forbid(principal, action, resource) when { context.state_changing && context.copied_control };

@id("R3")
forbid(principal, action, resource) when { context.prod && context.freeze && context.writes_data };

@id("R4")
forbid(principal, action, resource) when { context.prod && context.sql_write && context.ddl };

@id("R5")
forbid(principal, action, resource) when { context.over_hard_cap };

@id("R9")
forbid(principal, action, resource) when { context.file_read && context.sensitive_path };

@id("R12")
forbid(principal, action, resource) when { context.outside_workspace };

@id("R13")
forbid(principal, action, resource) when { context.web_fetch && context.unknown_host && context.url_carries_private };

@id("R19")
forbid(principal, action, resource) when { context.ap_release && context.self_proposed };

@id("R20")
forbid(principal, action, resource) when { context.bank_change && context.iban_untrusted };

@id("R21")
forbid(principal, action, resource) when { context.ap_release && context.sanctioned };

@id("R22")
forbid(principal, action, resource) when { context.sql_write && context.deletes_retained };

@id("R28")
forbid(principal, action, resource) when { context.outbound && context.carries_canary };

// ---------------------------------------------------------------- approval floors (a person decides)
@id("R1")
forbid(principal, action == Action::"auto_execute", resource) when { context.ingress && context.untrusted_control };

@id("R2")
forbid(principal, action == Action::"auto_execute", resource)
  when { context.external_send && !context.all_internal && context.pii_out > context.pii_external_max };

@id("R5")
forbid(principal, action == Action::"auto_execute", resource) when { context.over_auto_limit };

@id("R6")
forbid(principal, action == Action::"auto_execute", resource) when { context.draft_tool };

@id("R10")
forbid(principal, action == Action::"auto_execute", resource)
  when { context.prod && context.sql_write && context.rows_changed > context.bulk_rows_approval };

@id("R14")
forbid(principal, action == Action::"auto_execute", resource)
  when { context.external && context.private_seen && context.untrusted_seen && !context.destination_trusted
         && !context.internal_destination };

@id("R18")
forbid(principal, action == Action::"auto_execute", resource)
  when { context.ap_release && context.amount > context.role_release_limit };

@id("R25")
forbid(principal, action == Action::"auto_execute", resource) when { context.lookalike };
