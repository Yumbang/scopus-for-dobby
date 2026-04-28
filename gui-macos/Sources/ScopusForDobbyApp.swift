import SwiftUI

@main
struct ScopusForDobbyApp: App {
    @StateObject private var state = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(state)
                .frame(minWidth: 900, minHeight: 540)
                .task { await state.bootstrap() }
        }
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}
