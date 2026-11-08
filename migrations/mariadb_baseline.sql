-- Frozen schema at 121313f47a90. Future changes belong in Alembic revisions.

CREATE TABLE audit_events (
	id VARCHAR(128) NOT NULL, 
	action VARCHAR(128) NOT NULL, 
	outcome LONGTEXT NOT NULL, 
	occurred_at DOUBLE NOT NULL, 
	recorded_at DOUBLE NOT NULL, 
	scopes JSON NOT NULL, 
	fields JSON NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_audit_event_outcome CHECK (outcome IN ('succeeded', 'denied', 'failed'))
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_audit_events_action ON audit_events (action);

CREATE INDEX ix_audit_events_occurred_at ON audit_events (occurred_at);

CREATE TABLE auth_settings (
	id INTEGER NOT NULL, 
	registration_code_required BOOL NOT NULL, 
	approval_notification_debounce_seconds INTEGER NOT NULL, 
	approval_notifications_enabled BOOL NOT NULL, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE companion_pins (
	user_id VARCHAR(128) NOT NULL, 
	pin_hash LONGTEXT NOT NULL, 
	PRIMARY KEY (user_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE deleted_content (
	kind VARCHAR(128) NOT NULL, 
	identifier VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	owner_id LONGTEXT NOT NULL, 
	deleted_by LONGTEXT NOT NULL, 
	deleted_at DOUBLE NOT NULL, 
	purge_after DOUBLE NOT NULL, 
	purged_at DOUBLE, 
	account_id VARCHAR(128), 
	details JSON NOT NULL, 
	PRIMARY KEY (kind, identifier)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_deleted_content_account_id ON deleted_content (account_id);

CREATE INDEX ix_deleted_content_purge_after ON deleted_content (purge_after);

CREATE TABLE label_templates (
	group_id VARCHAR(128), 
	scope VARCHAR(128) NOT NULL DEFAULT 'personal', 
	owner_id VARCHAR(128) NOT NULL DEFAULT 'local-owner', 
	id VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	revision INTEGER NOT NULL, 
	document JSON NOT NULL, 
	archived BOOL NOT NULL, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE locations (
	id VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	parent_id VARCHAR(128), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_location_not_own_parent CHECK (parent_id != id), 
	FOREIGN KEY(parent_id) REFERENCES locations (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_locations_parent_id ON locations (parent_id);

CREATE TABLE notification_endpoints (
	id VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	transport LONGTEXT NOT NULL DEFAULT 'ntfy', 
	email LONGTEXT NOT NULL DEFAULT '', 
	owner_id VARCHAR(128), 
	push_subscription JSON NOT NULL DEFAULT '{}', 
	push_session_hash VARCHAR(128), 
	url LONGTEXT NOT NULL, 
	topic LONGTEXT NOT NULL, 
	token LONGTEXT NOT NULL, 
	enabled BOOL NOT NULL, 
	destination_ids JSON NOT NULL, 
	all_printers BOOL NOT NULL DEFAULT '0', 
	priorities JSON NOT NULL, 
	kinds JSON NOT NULL, 
	printer_kinds JSON NOT NULL DEFAULT '{}', 
	printer_priorities JSON NOT NULL DEFAULT '{}', 
	revision INTEGER NOT NULL, 
	created_at DOUBLE NOT NULL, 
	deleted_at DOUBLE, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_notification_endpoints_owner_id ON notification_endpoints (owner_id);

CREATE TABLE price_quotes (
	id VARCHAR(128) NOT NULL, 
	user_id LONGTEXT NOT NULL, 
	geometry_key LONGTEXT NOT NULL, 
	quotes JSON NOT NULL, 
	expires_at DOUBLE NOT NULL, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE print_requests (
	requested_by JSON, 
	id VARCHAR(128) NOT NULL, 
	owner_id VARCHAR(128) NOT NULL, 
	destination_id LONGTEXT NOT NULL, 
	kind LONGTEXT NOT NULL, 
	run_id VARCHAR(128), 
	request_key VARCHAR(128), 
	request_hash LONGTEXT NOT NULL, 
	status LONGTEXT NOT NULL, 
	revision INTEGER NOT NULL DEFAULT '1', 
	labels JSON NOT NULL, 
	job_ids JSON NOT NULL, 
	created_at DOUBLE NOT NULL, 
	decided_at DOUBLE, 
	decided_by LONGTEXT, 
	reason LONGTEXT, 
	PRIMARY KEY (id), 
	UNIQUE (owner_id, request_key), 
	UNIQUE (run_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_print_requests_owner_id ON print_requests (owner_id);

CREATE TABLE printer_groups (
	id VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	printer_ids JSON NOT NULL, 
	automatic_printing_held BOOL NOT NULL DEFAULT '0', 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE queue_destination_changes (
	id VARCHAR(128) NOT NULL, 
	job_id VARCHAR(128) NOT NULL, 
	run_id VARCHAR(128), 
	job_name LONGTEXT NOT NULL, 
	copy_ids JSON NOT NULL, 
	actor JSON NOT NULL, 
	source_id VARCHAR(128) NOT NULL, 
	target_id VARCHAR(128) NOT NULL, 
	source JSON NOT NULL, 
	target JSON NOT NULL, 
	previous_assignment JSON, 
	reason LONGTEXT NOT NULL, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_queue_destination_changes_created_at ON queue_destination_changes (created_at);

CREATE INDEX ix_queue_destination_changes_job_id ON queue_destination_changes (job_id);

CREATE INDEX ix_queue_destination_changes_source_id ON queue_destination_changes (source_id);

CREATE INDEX ix_queue_destination_changes_target_id ON queue_destination_changes (target_id);

CREATE TABLE release_migrations (
	version VARCHAR(128) NOT NULL, 
	draft JSON NOT NULL, 
	completed_at DOUBLE, 
	completed_by LONGTEXT, 
	PRIMARY KEY (version)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE request_digest (
	id INTEGER NOT NULL, 
	first_at DOUBLE NOT NULL, 
	due_at DOUBLE NOT NULL, 
	count INTEGER NOT NULL, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE resource_grants (
	principal_kind VARCHAR(128) NOT NULL, 
	principal_id VARCHAR(128) NOT NULL, 
	scope_kind VARCHAR(128) NOT NULL, 
	scope_id VARCHAR(128) NOT NULL, 
	permission VARCHAR(128) NOT NULL, 
	PRIMARY KEY (principal_kind, principal_id, scope_kind, scope_id, permission), 
	CONSTRAINT ck_grant_principal_kind CHECK (principal_kind IN ('user', 'role')), 
	CONSTRAINT ck_grant_scope_kind CHECK (scope_kind IN ('printer', 'printer_group', 'cartridge', 'location', 'companion'))
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE resource_ownership (
	id VARCHAR(128) NOT NULL, 
	kind LONGTEXT NOT NULL, 
	resource_id VARCHAR(128) NOT NULL, 
	owner_id LONGTEXT NOT NULL, 
	owner_name LONGTEXT NOT NULL, 
	effective_at DOUBLE NOT NULL, 
	ended_at DOUBLE, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_resource_ownership_resource_id ON resource_ownership (resource_id);

CREATE TABLE roles (
	id VARCHAR(128) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	permissions JSON NOT NULL, 
	protected BOOL NOT NULL DEFAULT '0', 
	PRIMARY KEY (id), 
	UNIQUE (name)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE tape_profiles (
	id VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	width_mm DOUBLE NOT NULL, 
	foreground LONGTEXT NOT NULL, 
	background LONGTEXT NOT NULL, 
	auto_print_threshold INTEGER NOT NULL, 
	waiting_notification_enabled BOOL NOT NULL, 
	waiting_notification_interval_seconds INTEGER NOT NULL, 
	reminder_silenced BOOL NOT NULL, 
	reminder_snoozed_until DOUBLE, 
	reminder_last_at DOUBLE, 
	reminder_episode INTEGER NOT NULL, 
	reminder_active BOOL NOT NULL, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE usage_adjustments (
	id VARCHAR(128) NOT NULL, 
	user_id VARCHAR(128) NOT NULL, 
	username LONGTEXT NOT NULL, 
	actor_id LONGTEXT NOT NULL, 
	actor_name LONGTEXT NOT NULL, 
	amount_minor INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	note LONGTEXT NOT NULL, 
	created_at DOUBLE NOT NULL, 
	recipient_id VARCHAR(128), 
	recipient_name LONGTEXT, 
	cartridge_allocations JSON NOT NULL DEFAULT '{}', 
	requested_allocations JSON, 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_usage_adjustments_recipient_id ON usage_adjustments (recipient_id);

CREATE INDEX ix_usage_adjustments_user_id ON usage_adjustments (user_id);

CREATE TABLE user_groups (
	id VARCHAR(128) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	members JSON NOT NULL DEFAULT '[]', 
	PRIMARY KEY (id), 
	UNIQUE (name)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE users (
	id VARCHAR(128) NOT NULL, 
	username VARCHAR(128) NOT NULL, 
	password_hash LONGTEXT NOT NULL, 
	disabled BOOL NOT NULL, 
	role_ids JSON NOT NULL, 
	created_at DOUBLE NOT NULL, 
	last_seen_version LONGTEXT, 
	email LONGTEXT, 
	PRIMARY KEY (id), 
	UNIQUE (username)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE access_change_confirmations (
	token_hash VARCHAR(128) NOT NULL, 
	actor_id VARCHAR(128) NOT NULL, 
	request_hash LONGTEXT NOT NULL, 
	state_hash LONGTEXT NOT NULL, 
	expires_at DOUBLE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE auth_sessions (
	token_hash VARCHAR(128) NOT NULL, 
	id VARCHAR(128) NOT NULL, 
	user_id VARCHAR(128) NOT NULL, 
	csrf_token LONGTEXT NOT NULL, 
	created_at DOUBLE NOT NULL, 
	expires_at DOUBLE NOT NULL, 
	last_seen_at DOUBLE, 
	ip_address LONGTEXT, 
	user_agent LONGTEXT, 
	location LONGTEXT, 
	PRIMARY KEY (token_hash), 
	UNIQUE (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);

CREATE TABLE cartridges (
	id VARCHAR(128) NOT NULL, 
	archived BOOL NOT NULL DEFAULT '0', 
	profile_id VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	nominal_length_mm DOUBLE NOT NULL, 
	remaining_mm DOUBLE NOT NULL, 
	consumption_uncertain BOOL NOT NULL, 
	price_minor INTEGER, 
	currency VARCHAR(3) NOT NULL DEFAULT 'EUR', 
	owner_id VARCHAR(128), 
	location_id VARCHAR(128), 
	notes LONGTEXT NOT NULL DEFAULT '', 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES tape_profiles (id), 
	FOREIGN KEY(location_id) REFERENCES locations (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_cartridges_location_id ON cartridges (location_id);

CREATE INDEX ix_cartridges_owner_id ON cartridges (owner_id);

CREATE TABLE companions (
	id VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	location_id VARCHAR(128) NOT NULL, 
	bound_user_id VARCHAR(128), 
	key_hash VARCHAR(128), 
	revision INTEGER NOT NULL, 
	created_at DOUBLE NOT NULL, 
	last_seen_at DOUBLE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(location_id) REFERENCES locations (id), 
	UNIQUE (key_hash)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE notifications (
	kind VARCHAR(128) NOT NULL DEFAULT 'general', 
	context JSON NOT NULL DEFAULT '{}', 
	recipient_id VARCHAR(128) NOT NULL DEFAULT 'local-owner', 
	id VARCHAR(128) NOT NULL, 
	title LONGTEXT NOT NULL, 
	message LONGTEXT NOT NULL, 
	path LONGTEXT NOT NULL, 
	profile_id VARCHAR(128), 
	episode INTEGER, 
	created_at DOUBLE NOT NULL, 
	next_attempt_at DOUBLE NOT NULL, 
	attempts INTEGER NOT NULL, 
	delivered_at DOUBLE, 
	cancelled BOOL NOT NULL, 
	last_error LONGTEXT, 
	routed_at DOUBLE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES tape_profiles (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE print_runs (
	assigned_printer_id VARCHAR(128), 
	destination_id VARCHAR(128) NOT NULL DEFAULT 'main', 
	owner_id VARCHAR(128) NOT NULL DEFAULT 'local-owner', 
	id VARCHAR(128) NOT NULL, 
	request_key VARCHAR(128) NOT NULL, 
	request_hash LONGTEXT NOT NULL, 
	name LONGTEXT NOT NULL, 
	profile_id VARCHAR(128) NOT NULL, 
	manifest JSON NOT NULL, 
	created_at DOUBLE NOT NULL, 
	submitted_at DOUBLE, 
	PRIMARY KEY (id), 
	UNIQUE (request_key), 
	FOREIGN KEY(profile_id) REFERENCES tape_profiles (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE printers (
	id VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	driver LONGTEXT NOT NULL, 
	config JSON NOT NULL, 
	owner_id VARCHAR(128), 
	location_id VARCHAR(128), 
	PRIMARY KEY (id), 
	FOREIGN KEY(location_id) REFERENCES locations (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_printers_location_id ON printers (location_id);

CREATE INDEX ix_printers_owner_id ON printers (owner_id);

CREATE TABLE recovery_tokens (
	token_hash VARCHAR(128) NOT NULL, 
	user_id VARCHAR(128) NOT NULL, 
	purpose LONGTEXT NOT NULL, 
	email LONGTEXT NOT NULL, 
	password_fingerprint LONGTEXT NOT NULL, 
	expires_at DOUBLE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_recovery_tokens_expires_at ON recovery_tokens (expires_at);

CREATE INDEX ix_recovery_tokens_user_id ON recovery_tokens (user_id);

CREATE TABLE registration_codes (
	id VARCHAR(128) NOT NULL, 
	token_hash VARCHAR(128) NOT NULL, 
	name LONGTEXT NOT NULL, 
	role_ids JSON NOT NULL, 
	group_ids JSON NOT NULL, 
	group_permissions JSON NOT NULL DEFAULT '{}', 
	created_at DOUBLE NOT NULL, 
	expires_at DOUBLE NOT NULL, 
	redeemed_at DOUBLE, 
	redeemed_by VARCHAR(128), 
	revoked BOOL NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (token_hash), 
	FOREIGN KEY(redeemed_by) REFERENCES users (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE template_revisions (
	template_id VARCHAR(128) NOT NULL, 
	revision INTEGER NOT NULL, 
	name LONGTEXT NOT NULL, 
	document JSON NOT NULL, 
	created_at DOUBLE, 
	edited_by JSON, 
	restored_from_revision INTEGER, 
	PRIMARY KEY (template_id, revision), 
	FOREIGN KEY(template_id) REFERENCES label_templates (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE batches (
	`trigger` JSON, 
	print_plan JSON, 
	consumption_source VARCHAR(128), 
	printer_id VARCHAR(128) NOT NULL DEFAULT 'main', 
	id VARCHAR(128) NOT NULL, 
	cartridge_id VARCHAR(128) NOT NULL, 
	state ENUM('QUEUED','PRINTING','PRINTED','NEEDS_REVIEW','CANCELLED','FAILED') NOT NULL, 
	created_at DOUBLE NOT NULL, 
	finished_at DOUBLE, 
	completion_notified_at DOUBLE, 
	error LONGTEXT, 
	estimated_mm DOUBLE NOT NULL, 
	consumed_mm DOUBLE, 
	shortage_warning BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cartridge_id) REFERENCES cartridges (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE companion_printers (
	printer_id VARCHAR(128) NOT NULL, 
	companion_id VARCHAR(128) NOT NULL, 
	local_id LONGTEXT NOT NULL, 
	enabled BOOL NOT NULL, 
	status JSON NOT NULL, 
	last_seen_at DOUBLE, 
	blocked BOOL NOT NULL, 
	clearance INTEGER NOT NULL, 
	PRIMARY KEY (printer_id), 
	FOREIGN KEY(printer_id) REFERENCES printers (id), 
	FOREIGN KEY(companion_id) REFERENCES companions (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_companion_printers_companion_id ON companion_printers (companion_id);

CREATE TABLE companion_sessions (
	token_hash VARCHAR(128) NOT NULL, 
	companion_id VARCHAR(128) NOT NULL, 
	user_id LONGTEXT NOT NULL, 
	revision INTEGER NOT NULL, 
	pin_fingerprint LONGTEXT, 
	expires_at DOUBLE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(companion_id) REFERENCES companions (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_companion_sessions_companion_id ON companion_sessions (companion_id);

CREATE TABLE flush_requests (
	started_by JSON, 
	use_authorizations JSON NOT NULL DEFAULT '{}', 
	printer_id VARCHAR(128) NOT NULL DEFAULT 'main', 
	destination_id VARCHAR(128) NOT NULL DEFAULT 'main', 
	id VARCHAR(128) NOT NULL, 
	cartridge_id VARCHAR(128) NOT NULL, 
	copy_ids JSON NOT NULL, 
	created_at DOUBLE NOT NULL, 
	completed BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cartridge_id) REFERENCES cartridges (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE notification_deliveries (
	id VARCHAR(128) NOT NULL, 
	notification_id VARCHAR(128) NOT NULL, 
	endpoint_id VARCHAR(128) NOT NULL, 
	endpoint_revision INTEGER NOT NULL, 
	endpoint_name LONGTEXT NOT NULL, 
	attempts INTEGER NOT NULL, 
	next_attempt_at DOUBLE NOT NULL, 
	delivered_at DOUBLE, 
	cancelled BOOL NOT NULL, 
	last_error LONGTEXT, 
	PRIMARY KEY (id), 
	UNIQUE (notification_id, endpoint_id), 
	FOREIGN KEY(notification_id) REFERENCES notifications (id), 
	FOREIGN KEY(endpoint_id) REFERENCES notification_endpoints (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_notification_deliveries_notification_id ON notification_deliveries (notification_id);

CREATE TABLE notification_reads (
	notification_id VARCHAR(128) NOT NULL, 
	user_id VARCHAR(128) NOT NULL, 
	read_at DOUBLE NOT NULL, 
	PRIMARY KEY (notification_id, user_id), 
	FOREIGN KEY(notification_id) REFERENCES notifications (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE print_jobs (
	attribution JSON, 
	authorization_basis VARCHAR(128) NOT NULL DEFAULT 'print', 
	destination_id VARCHAR(128) NOT NULL DEFAULT 'main', 
	owner_id VARCHAR(128) NOT NULL DEFAULT 'local-owner', 
	id VARCHAR(128) NOT NULL, 
	profile_id VARCHAR(128) NOT NULL, 
	template_id LONGTEXT NOT NULL, 
	run_id VARCHAR(128), 
	run_position INTEGER, 
	source_row INTEGER, 
	template_snapshot JSON NOT NULL, 
	payload JSON NOT NULL, 
	width_mm DOUBLE NOT NULL, 
	length_mm DOUBLE NOT NULL, 
	copies INTEGER NOT NULL, 
	notify_on_completion BOOL NOT NULL DEFAULT '1', 
	completion_notified_at DOUBLE, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(profile_id) REFERENCES tape_profiles (id), 
	FOREIGN KEY(run_id) REFERENCES print_runs (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_print_jobs_profile_id ON print_jobs (profile_id);

CREATE INDEX ix_print_jobs_run_id ON print_jobs (run_id);

CREATE TABLE printer_state (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	printer_id VARCHAR(128) NOT NULL DEFAULT 'main', 
	active_cartridge_id VARCHAR(128), 
	media_confirmation JSON, 
	media_verified_fingerprint VARCHAR(128), 
	cartridge_check_enabled BOOL NOT NULL DEFAULT '1', 
	cartridge_check_pending BOOL NOT NULL DEFAULT '0', 
	empty_alert_cartridge_id VARCHAR(128), 
	blocker LONGTEXT, 
	automatic_printing_held BOOL NOT NULL DEFAULT '0', 
	PRIMARY KEY (id), 
	UNIQUE (printer_id), 
	FOREIGN KEY(active_cartridge_id) REFERENCES cartridges (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE cartridge_quote_offers (
	id VARCHAR(128) NOT NULL, 
	job_id VARCHAR(128) NOT NULL, 
	printer_id VARCHAR(128) NOT NULL, 
	cartridge_id LONGTEXT NOT NULL, 
	requester_id VARCHAR(128) NOT NULL, 
	actor_id LONGTEXT NOT NULL, 
	status LONGTEXT NOT NULL, 
	acceptance JSON, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES print_jobs (id), 
	FOREIGN KEY(printer_id) REFERENCES printers (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_cartridge_quote_offers_job_id ON cartridge_quote_offers (job_id);

CREATE INDEX ix_cartridge_quote_offers_requester_id ON cartridge_quote_offers (requester_id);

CREATE TABLE companion_batches (
	batch_id VARCHAR(128) NOT NULL, 
	companion_id VARCHAR(128) NOT NULL, 
	printer_id VARCHAR(128) NOT NULL, 
	payload JSON NOT NULL, 
	digest LONGTEXT NOT NULL, 
	go_token LONGTEXT, 
	result JSON, 
	stop_mode LONGTEXT, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (batch_id), 
	FOREIGN KEY(batch_id) REFERENCES batches (id), 
	FOREIGN KEY(companion_id) REFERENCES companions (id), 
	FOREIGN KEY(printer_id) REFERENCES printers (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_companion_batches_companion_id ON companion_batches (companion_id);

CREATE TABLE job_access_holds (
	resolved_by_snapshot JSON, 
	job_id VARCHAR(128) NOT NULL, 
	reason LONGTEXT NOT NULL, 
	held_at DOUBLE NOT NULL, 
	status VARCHAR(128) NOT NULL, 
	resolved_at DOUBLE, 
	resolved_by LONGTEXT, 
	PRIMARY KEY (job_id), 
	FOREIGN KEY(job_id) REFERENCES print_jobs (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE job_submissions (
	owner_id VARCHAR(128) NOT NULL, 
	request_key VARCHAR(128) NOT NULL, 
	request_hash LONGTEXT NOT NULL, 
	job_id VARCHAR(128) NOT NULL, 
	PRIMARY KEY (owner_id, request_key), 
	FOREIGN KEY(job_id) REFERENCES print_jobs (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE label_copies (
	id VARCHAR(128) NOT NULL, 
	job_id VARCHAR(128) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	state ENUM('QUEUED','PRINTING','PRINTED','NEEDS_REVIEW','CANCELLED','FAILED') NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES print_jobs (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_label_copies_job_id ON label_copies (job_id);

CREATE INDEX ix_label_copies_state ON label_copies (state);

CREATE TABLE retry_offers (
	id VARCHAR(128) NOT NULL, 
	request_key VARCHAR(128) NOT NULL, 
	request_hash LONGTEXT NOT NULL, 
	batch_id VARCHAR(128) NOT NULL, 
	source_job_id VARCHAR(128) NOT NULL, 
	copy_ids JSON NOT NULL, 
	requester_id VARCHAR(128) NOT NULL, 
	actor_id LONGTEXT NOT NULL, 
	actor_name LONGTEXT NOT NULL, 
	mode LONGTEXT NOT NULL, 
	cartridge_id VARCHAR(128), 
	status VARCHAR(128) NOT NULL, 
	job_id VARCHAR(128), 
	created_at DOUBLE NOT NULL, 
	accepted_at DOUBLE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(batch_id) REFERENCES batches (id), 
	FOREIGN KEY(source_job_id) REFERENCES print_jobs (id), 
	FOREIGN KEY(job_id) REFERENCES print_jobs (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_retry_offers_batch_id ON retry_offers (batch_id);

CREATE INDEX ix_retry_offers_request_key ON retry_offers (request_key);

CREATE INDEX ix_retry_offers_requester_id ON retry_offers (requester_id);

CREATE TABLE tape_allocations (
	batch_id VARCHAR(128) NOT NULL, 
	user_id VARCHAR(128) NOT NULL, 
	username LONGTEXT NOT NULL, 
	planned_mm DOUBLE NOT NULL, 
	consumed_mm DOUBLE, 
	nominal_length_mm DOUBLE NOT NULL, 
	price_minor INTEGER, 
	currency VARCHAR(3) NOT NULL, 
	cost_micros VARCHAR(128), 
	cartridge_id VARCHAR(128), 
	recipient_id VARCHAR(128), 
	recipient_name LONGTEXT, 
	charged_micros VARCHAR(128), 
	recipient_assigned_at DOUBLE, 
	PRIMARY KEY (batch_id, user_id), 
	FOREIGN KEY(batch_id) REFERENCES batches (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE INDEX ix_tape_allocations_recipient_id ON tape_allocations (recipient_id);

CREATE INDEX ix_tape_allocations_user_id ON tape_allocations (user_id);

CREATE TABLE unit_charges (
	batch_id VARCHAR(128) NOT NULL, 
	job_id VARCHAR(128) NOT NULL, 
	planned_mm DOUBLE NOT NULL, 
	currency LONGTEXT NOT NULL, 
	reserved_micros LONGTEXT, 
	cap_micros LONGTEXT, 
	actual_micros LONGTEXT, 
	charged_micros LONGTEXT, 
	authorization JSON, 
	PRIMARY KEY (batch_id, job_id), 
	FOREIGN KEY(batch_id) REFERENCES batches (id), 
	FOREIGN KEY(job_id) REFERENCES print_jobs (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;

CREATE TABLE batch_items (
	attribution JSON, 
	batch_id VARCHAR(128) NOT NULL, 
	copy_id VARCHAR(128) NOT NULL, 
	`position` INTEGER NOT NULL, 
	outcome ENUM('QUEUED','PRINTING','PRINTED','NEEDS_REVIEW','CANCELLED','FAILED') NOT NULL, 
	PRIMARY KEY (batch_id, copy_id), 
	FOREIGN KEY(batch_id) REFERENCES batches (id), 
	FOREIGN KEY(copy_id) REFERENCES label_copies (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_nopad_bin;
