import 'package:fatigue_monitor_ui/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('parses a structured desktop notice', () {
    final notice = parseDesktopNotice(const {
      'id': 4,
      'level': 'info',
      'message': '自動採集完成',
    });

    expect(notice?.id, 4);
    expect(notice?.level, 'info');
    expect(notice?.message, '自動採集完成');
  });

  test('ignores malformed desktop notices', () {
    expect(parseDesktopNotice(const {'id': 4.5, 'message': 'bad'}), isNull);
    expect(parseDesktopNotice(const {'id': 4, 'message': '  '}), isNull);
    expect(parseDesktopNotice(const {'id': 4}), isNull);
  });

  test('normalizes unknown notice levels to errors', () {
    expect(
      parseDesktopNotice(const {'id': 5, 'level': 'debug', 'message': 'oops'})
          ?.level,
      'error',
    );
  });
}
