import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

import '../core/api_error.dart';
import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';

class PodOrderScreen extends ConsumerStatefulWidget {
  const PodOrderScreen({
    super.key,
    required this.bookId,
    required this.bookTitle,
  });

  final String bookId;
  final String bookTitle;

  @override
  ConsumerState<PodOrderScreen> createState() => _PodOrderScreenState();
}

class _PodOrderScreenState extends ConsumerState<PodOrderScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _line1Controller = TextEditingController();
  final _postalController = TextEditingController();
  final _countryController = TextEditingController(text: 'KR');
  final _phoneController = TextEditingController();

  int _quantity = 1;
  bool _isSubmitting = false;
  bool _isRefreshingOrder = false;
  String? _errorMessage;
  Map<String, dynamic>? _createdOrder;
  Map<String, dynamic>? _orderDetail;

  @override
  void dispose() {
    _nameController.dispose();
    _line1Controller.dispose();
    _postalController.dispose();
    _countryController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  int get _estimatedTotal => (18000 * _quantity) + 3000;

  Future<void> _submitOrder() async {
    if (_isSubmitting) {
      return;
    }
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });
    try {
      final api = ref.read(apiClientProvider);
      final created = await api.createPodOrder(
        bookId: widget.bookId,
        quantity: _quantity,
        shippingAddress: {
          'name': _nameController.text.trim(),
          'line1': _line1Controller.text.trim(),
          'postal_code': _postalController.text.trim(),
          'country': _countryController.text.trim(),
          'phone': _phoneController.text.trim(),
        },
      );

      final orderId = created['order_id']?.toString();
      Map<String, dynamic>? detail;
      if (orderId != null && orderId.isNotEmpty) {
        detail = await api.getPodOrder(orderId);
      }

      if (!mounted) {
        return;
      }
      setState(() {
        _createdOrder = created;
        _orderDetail = detail;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(AppLocalizations.of(context).podOrderSubmitSuccess)),
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      final message = error is ApiError
          ? error.userMessage
          : AppLocalizations.of(context).podOrderSubmitError;
      setState(() => _errorMessage = message);
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _refreshOrderDetail() async {
    final orderId = _createdOrder?['order_id']?.toString();
    if (orderId == null || orderId.isEmpty || _isRefreshingOrder) {
      return;
    }

    setState(() => _isRefreshingOrder = true);
    try {
      final api = ref.read(apiClientProvider);
      final detail = await api.getPodOrder(orderId);
      if (!mounted) {
        return;
      }
      setState(() => _orderDetail = detail);
    } catch (error) {
      if (!mounted) {
        return;
      }
      final message = error is ApiError
          ? error.userMessage
          : AppLocalizations.of(context).podOrderStatusError;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message)),
      );
    } finally {
      if (mounted) {
        setState(() => _isRefreshingOrder = false);
      }
    }
  }

  int _toInt(dynamic value, {int fallback = 0}) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    if (value is String) {
      return int.tryParse(value) ?? fallback;
    }
    return fallback;
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final orderId = _createdOrder?['order_id']?.toString();
    final providerOrderId = _orderDetail?['provider_order_id']?.toString() ??
        _createdOrder?['provider_order_id']?.toString();
    final orderStatus = _orderDetail?['status']?.toString() ??
        _createdOrder?['status']?.toString() ??
        '-';
    final syncSource = _orderDetail?['sync_source']?.toString() ??
        _createdOrder?['sync_source']?.toString() ??
        'local';
    final totalPrice = _toInt(_orderDetail?['total_price'],
        fallback: _toInt(_createdOrder?['total_price']));

    return Scaffold(
      appBar: AppBar(
        title: Text(l.podOrderTitle),
      ),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.md),
        children: [
          Container(
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(AppRadius.md),
              border: Border.all(color: AppColors.divider),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(l.podOrderBookLabel, style: AppTextStyles.caption),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  widget.bookTitle.isEmpty ? widget.bookId : widget.bookTitle,
                  style: AppTextStyles.heading3,
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Form(
            key: _formKey,
            child: Column(
              children: [
                TextFormField(
                  controller: _nameController,
                  decoration: InputDecoration(
                    labelText: l.podOrderRecipientNameLabel,
                  ),
                  validator: (value) => (value?.trim().isEmpty ?? true)
                      ? l.podOrderRecipientNameError
                      : null,
                ),
                const SizedBox(height: AppSpacing.md),
                TextFormField(
                  controller: _line1Controller,
                  decoration: InputDecoration(
                    labelText: l.podOrderAddressLabel,
                  ),
                  validator: (value) => (value?.trim().isEmpty ?? true)
                      ? l.podOrderAddressError
                      : null,
                ),
                const SizedBox(height: AppSpacing.md),
                Row(
                  children: [
                    Expanded(
                      child: TextFormField(
                        controller: _postalController,
                        decoration:
                            InputDecoration(labelText: l.podOrderPostalLabel),
                        validator: (value) => (value?.trim().isEmpty ?? true)
                            ? l.podOrderPostalError
                            : null,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: TextFormField(
                        controller: _countryController,
                        decoration:
                            InputDecoration(labelText: l.podOrderCountryLabel),
                        validator: (value) => (value?.trim().isEmpty ?? true)
                            ? l.podOrderCountryError
                            : null,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                TextFormField(
                  controller: _phoneController,
                  decoration: InputDecoration(labelText: l.podOrderPhoneLabel),
                  validator: (value) => (value?.trim().isEmpty ?? true)
                      ? l.podOrderPhoneError
                      : null,
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Container(
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(AppRadius.md),
              border: Border.all(color: AppColors.divider),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(l.podOrderQuantityLabel, style: AppTextStyles.caption),
                const SizedBox(height: AppSpacing.xs),
                Row(
                  children: [
                    IconButton(
                      tooltip: l.podOrderDecreaseQuantityTooltip,
                      onPressed: _quantity <= 1
                          ? null
                          : () => setState(() => _quantity -= 1),
                      icon: const Icon(Icons.remove_circle_outline),
                    ),
                    Text(l.podOrderQuantityValue(_quantity),
                        style: AppTextStyles.heading3),
                    IconButton(
                      tooltip: l.podOrderIncreaseQuantityTooltip,
                      onPressed: _quantity >= 10
                          ? null
                          : () => setState(() => _quantity += 1),
                      icon: const Icon(Icons.add_circle_outline),
                    ),
                    const Spacer(),
                    Text(
                      l.podOrderEstimatedTotal(_estimatedTotal),
                      style: AppTextStyles.bodySmall,
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          ElevatedButton.icon(
            onPressed: _isSubmitting ? null : _submitOrder,
            icon: _isSubmitting
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.local_shipping_outlined),
            label: Text(
                _isSubmitting ? l.podOrderSubmitting : l.podOrderSubmitButton),
          ),
          if (_errorMessage != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(
              _errorMessage!,
              style: AppTextStyles.bodySmall.copyWith(color: AppColors.error),
            ),
          ],
          if (orderId != null) ...[
            const SizedBox(height: AppSpacing.lg),
            Container(
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(AppRadius.md),
                border: Border.all(color: AppColors.divider),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l.podOrderStatusTitle, style: AppTextStyles.heading3),
                  const SizedBox(height: AppSpacing.sm),
                  Text(l.podOrderOrderNumber(orderId),
                      style: AppTextStyles.bodySmall),
                  if (providerOrderId != null && providerOrderId.isNotEmpty)
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            l.podOrderProviderOrderNumber(providerOrderId),
                            style: AppTextStyles.bodySmall,
                          ),
                        ),
                        IconButton(
                          tooltip: l.podOrderCopyTooltip,
                          onPressed: () async {
                            final messenger = ScaffoldMessenger.of(context);
                            await Clipboard.setData(
                              ClipboardData(text: providerOrderId),
                            );
                            messenger.showSnackBar(
                              SnackBar(
                                  content: Text(l.podOrderProviderOrderCopied)),
                            );
                          },
                          icon: const Icon(Icons.copy, size: 18),
                        ),
                      ],
                    ),
                  Text(l.podOrderStatusValue(orderStatus),
                      style: AppTextStyles.bodySmall),
                  Text(l.podOrderPaymentAmount(totalPrice),
                      style: AppTextStyles.bodySmall),
                  Text(l.podOrderSyncValue(syncSource),
                      style: AppTextStyles.bodySmall),
                  if ((_orderDetail?['tracking_number']
                          ?.toString()
                          .isNotEmpty ??
                      false))
                    Text(
                      l.podOrderTrackingNumber(
                          _orderDetail!['tracking_number'].toString()),
                      style: AppTextStyles.bodySmall,
                    ),
                  const SizedBox(height: AppSpacing.sm),
                  OutlinedButton.icon(
                    onPressed: _isRefreshingOrder ? null : _refreshOrderDetail,
                    icon: _isRefreshingOrder
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.refresh),
                    label: Text(l.podOrderRefreshStatus),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
