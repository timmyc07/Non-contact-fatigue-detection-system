part of '../main.dart';

class PanelPage extends StatelessWidget {
  const PanelPage({
    required this.title,
    required this.description,
    required this.children,
    this.trailing,
    super.key,
  });

  final String title;
  final String description;
  final Widget? trailing;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          key: PageStorageKey(title),
          padding: EdgeInsets.all(constraints.maxWidth < 700 ? 18 : 28),
          child: RepaintBoundary(
              child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1440),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Wrap(
                    alignment: WrapAlignment.spaceBetween,
                    runSpacing: 12,
                    spacing: 20,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      ConstrainedBox(
                        constraints: BoxConstraints(
                            maxWidth:
                                (constraints.maxWidth - 56).clamp(0, 900)),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(title,
                                style: Theme.of(context)
                                    .textTheme
                                    .headlineSmall
                                    ?.copyWith(
                                        fontWeight: FontWeight.w700,
                                        letterSpacing: -.5)),
                            const SizedBox(height: 6),
                            Text(description,
                                style: const TextStyle(
                                    color: kMutedInk, fontSize: 13)),
                          ],
                        ),
                      ),
                      if (trailing != null) trailing!,
                    ],
                  ),
                  const SizedBox(height: 24),
                  ...children,
                ],
              ),
            ),
          )),
        ),
      );
}

class PanelSectionTitle extends StatelessWidget {
  const PanelSectionTitle({required this.title, this.subtitle, super.key});
  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title,
              style:
                  const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
          if (subtitle != null) ...[
            const SizedBox(height: 5),
            Text(subtitle!,
                style: const TextStyle(color: kMutedInk, fontSize: 12)),
          ],
        ]),
      );
}
