import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

/// 只更新影像區；同一繪製週期的舊影格不需解碼或加入影像快取。
class LivePreviewImage extends StatefulWidget {
  const LivePreviewImage({
    required this.frames,
    required this.placeholder,
    super.key,
  });

  final Stream<String> frames;
  final Widget placeholder;

  @override
  State<LivePreviewImage> createState() => _LivePreviewImageState();
}

class _LivePreviewImageState extends State<LivePreviewImage> {
  StreamSubscription<String>? _subscription;
  MemoryImage? _image;
  String? _pending;
  int? _scheduledFrame;

  @override
  void initState() {
    super.initState();
    _listen();
  }

  @override
  void didUpdateWidget(covariant LivePreviewImage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.frames != widget.frames) {
      _stop();
      _image?.evict();
      _image = null;
      _listen();
    }
  }

  void _listen() {
    _subscription = widget.frames.listen((frame) {
      _pending = frame;
      _scheduledFrame ??= WidgetsBinding.instance.scheduleFrameCallback((_) {
        _scheduledFrame = null;
        final encoded = _pending;
        _pending = null;
        if (!mounted || encoded == null) return;
        try {
          final next = MemoryImage(base64Decode(encoded));
          final previous = _image;
          setState(() => _image = next);
          previous?.evict();
        } on FormatException {
          // 壞影格保留上一張畫面，等待後續串流。
        }
      });
    }, onError: (Object _) {});
  }

  void _stop() {
    _subscription?.cancel();
    if (_scheduledFrame case final id?) {
      WidgetsBinding.instance.cancelFrameCallbackWithId(id);
    }
    _scheduledFrame = null;
    _pending = null;
  }

  @override
  void dispose() {
    _stop();
    _image?.evict();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(
        child: _image == null
            ? widget.placeholder
            : Image(
                image: _image!,
                fit: BoxFit.contain,
                gaplessPlayback: true,
                filterQuality: FilterQuality.low,
                excludeFromSemantics: true,
                errorBuilder: (_, __, ___) => widget.placeholder,
              ),
      );
}
