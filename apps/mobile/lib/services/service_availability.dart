enum ServiceAvailabilityStatus {
  available,
  unsupported,
  misconfigured,
  unavailable,
}

class ServiceAvailability {
  const ServiceAvailability._(this.status, this.unavailableReason);

  const ServiceAvailability.available()
      : this._(ServiceAvailabilityStatus.available, null);

  const ServiceAvailability.unsupported(String reason)
      : this._(ServiceAvailabilityStatus.unsupported, reason);

  const ServiceAvailability.misconfigured(String reason)
      : this._(ServiceAvailabilityStatus.misconfigured, reason);

  const ServiceAvailability.unavailable(String reason)
      : this._(ServiceAvailabilityStatus.unavailable, reason);

  final ServiceAvailabilityStatus status;
  final String? unavailableReason;

  bool get isAvailable => status == ServiceAvailabilityStatus.available;
}
