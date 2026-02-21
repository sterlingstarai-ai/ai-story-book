import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

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
        const SnackBar(content: Text('주문이 접수되었습니다.')),
      );
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() => _errorMessage = '주문 접수에 실패했어요. 정보를 확인해주세요.');
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
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('주문 상태 조회에 실패했어요.')),
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
        title: const Text('실물책 주문'),
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
                const Text('주문 도서', style: AppTextStyles.caption),
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
                  decoration: const InputDecoration(
                    labelText: '수령인 이름',
                  ),
                  validator: (value) => (value?.trim().isEmpty ?? true)
                      ? '수령인 이름을 입력해주세요.'
                      : null,
                ),
                const SizedBox(height: AppSpacing.md),
                TextFormField(
                  controller: _line1Controller,
                  decoration: const InputDecoration(
                    labelText: '주소',
                  ),
                  validator: (value) =>
                      (value?.trim().isEmpty ?? true) ? '주소를 입력해주세요.' : null,
                ),
                const SizedBox(height: AppSpacing.md),
                Row(
                  children: [
                    Expanded(
                      child: TextFormField(
                        controller: _postalController,
                        decoration: const InputDecoration(labelText: '우편번호'),
                        validator: (value) => (value?.trim().isEmpty ?? true)
                            ? '우편번호를 입력해주세요.'
                            : null,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: TextFormField(
                        controller: _countryController,
                        decoration: const InputDecoration(labelText: '국가코드'),
                        validator: (value) => (value?.trim().isEmpty ?? true)
                            ? '국가코드를 입력해주세요.'
                            : null,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                TextFormField(
                  controller: _phoneController,
                  decoration: const InputDecoration(labelText: '연락처'),
                  validator: (value) =>
                      (value?.trim().isEmpty ?? true) ? '연락처를 입력해주세요.' : null,
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
                const Text('수량', style: AppTextStyles.caption),
                const SizedBox(height: AppSpacing.xs),
                Row(
                  children: [
                    IconButton(
                      onPressed: _quantity <= 1
                          ? null
                          : () => setState(() => _quantity -= 1),
                      icon: const Icon(Icons.remove_circle_outline),
                    ),
                    Text('$_quantity권', style: AppTextStyles.heading3),
                    IconButton(
                      onPressed: _quantity >= 10
                          ? null
                          : () => setState(() => _quantity += 1),
                      icon: const Icon(Icons.add_circle_outline),
                    ),
                    const Spacer(),
                    Text(
                      '예상 ${_estimatedTotal.toString()}원',
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
            label: Text(_isSubmitting ? '주문 처리 중...' : '주문하기'),
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
                  const Text('주문 상태', style: AppTextStyles.heading3),
                  const SizedBox(height: AppSpacing.sm),
                  Text('주문번호: $orderId', style: AppTextStyles.bodySmall),
                  if (providerOrderId != null && providerOrderId.isNotEmpty)
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            '공급사 주문번호: $providerOrderId',
                            style: AppTextStyles.bodySmall,
                          ),
                        ),
                        IconButton(
                          tooltip: '복사',
                          onPressed: () async {
                            final messenger = ScaffoldMessenger.of(context);
                            await Clipboard.setData(
                              ClipboardData(text: providerOrderId),
                            );
                            messenger.showSnackBar(
                              const SnackBar(content: Text('공급사 주문번호를 복사했어요.')),
                            );
                          },
                          icon: const Icon(Icons.copy, size: 18),
                        ),
                      ],
                    ),
                  Text('상태: $orderStatus', style: AppTextStyles.bodySmall),
                  Text('결제금액: ${totalPrice.toString()}원',
                      style: AppTextStyles.bodySmall),
                  Text('동기화: $syncSource', style: AppTextStyles.bodySmall),
                  if ((_orderDetail?['tracking_number']
                          ?.toString()
                          .isNotEmpty ??
                      false))
                    Text(
                      '운송장: ${_orderDetail!['tracking_number']}',
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
                    label: const Text('상태 새로고침'),
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
