import SwiftUI

struct CrewDashboardView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Theme.border.frame(height: 1)

            if state.crewAgents.isEmpty {
                EmptyCrewView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                TimelineView(.periodic(from: .now, by: 1)) { _ in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 10) {
                            if !state.crewGoal.isEmpty {
                                CrewGoalView(goal: state.crewGoal)
                            }
                            ForEach(state.crewAgents) { agent in
                                CrewAgentRow(agent: agent, elapsed: state.elapsed(for: agent))
                            }
                        }
                        .padding(14)
                    }
                }
                Theme.border.frame(height: 1)
                footer
            }
        }
        .background(Theme.sidebar)
    }

    private var header: some View {
        HStack(spacing: 9) {
            Image(systemName: "person.3")
                .font(.system(size: 13))
                .foregroundStyle(Theme.secondary)
            Text("Agents")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Theme.text)
            if !state.crewAgents.isEmpty {
                Text("\(state.crewAgents.count)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(Theme.tertiary)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(Theme.surfaceRaised, in: Capsule())
            }
            Spacer()
            if state.crewFinished {
                StatusDot(color: Theme.success)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
    }

    private var footer: some View {
        let counts = Dictionary(grouping: state.crewAgents, by: \.status).mapValues(\.count)
        return HStack(spacing: 8) {
            Text("\(state.crewOverallPercent)%")
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(Theme.text)
            ProgressView(value: Double(state.crewOverallPercent), total: 100)
                .progressViewStyle(.linear)
                .tint(Theme.accent)
            Text("\(counts["running", default: 0]) active")
                .font(.system(size: 11))
                .foregroundStyle(Theme.tertiary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }
}

private struct EmptyCrewView: View {
    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "person.3.sequence")
                .font(.system(size: 22))
                .foregroundStyle(Theme.tertiary)
            Text("Keine aktiven Agents")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Theme.secondary)
        }
    }
}

private struct CrewGoalView: View {
    let goal: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel(title: "Goal")
            Text(goal)
                .font(.system(size: 12.5))
                .foregroundStyle(Theme.secondary)
                .lineLimit(4)
        }
        .padding(10)
        .codexSurface(fill: Theme.surfaceInset)
    }
}

struct CrewAgentRow: View {
    let agent: CrewAgent
    let elapsed: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top, spacing: 9) {
                StatusDot(color: statusColor)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 3) {
                    Text(agent.role)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Theme.text)
                        .lineLimit(1)
                    if agent.title != agent.role {
                        Text(agent.title)
                            .font(.system(size: 12))
                            .foregroundStyle(Theme.tertiary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: 8)
                if elapsed > 0 {
                    Text("\(Int(elapsed))s")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(Theme.tertiary)
                }
            }

            ProgressView(value: agent.fraction, total: 1)
                .progressViewStyle(.linear)
                .tint(statusColor)

            HStack(spacing: 8) {
                Text("\(agent.percent)%")
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundStyle(statusColor)
                Text(activityText)
                    .font(.system(size: 11.5))
                    .foregroundStyle(agent.status == "failed" ? Theme.danger : Theme.tertiary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer()
            }
        }
        .padding(10)
        .codexSurface(fill: Theme.surface)
    }

    private var statusColor: Color {
        switch agent.status {
        case "running": return Theme.warning
        case "done": return Theme.success
        case "failed": return Theme.danger
        default: return Theme.tertiary
        }
    }

    private var activityText: String {
        switch agent.status {
        case "failed": return agent.error.isEmpty ? "fehlgeschlagen" : agent.error
        case "done": return "fertig"
        case "queued": return "wartet"
        default: return agent.activity.isEmpty ? "arbeitet" : agent.activity
        }
    }
}
