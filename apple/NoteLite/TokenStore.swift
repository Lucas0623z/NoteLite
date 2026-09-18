import Foundation
import Security

enum TokenStore {
    private static let service = "com.notelite.mobile.server-token"

    static func read(for configuration: ServerConfiguration) throws -> String {
        var query = identity(for: configuration)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return "" }
        guard status == errSecSuccess else { throw NoteLiteError.keychain(status) }
        guard let data = result as? Data, let token = String(data: data, encoding: .utf8) else {
            throw NoteLiteError.invalidResponse
        }
        return token
    }

    static func save(_ token: String, for configuration: ServerConfiguration) throws {
        let token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty, !token.contains("\r"), !token.contains("\n") else {
            throw NoteLiteError.missingToken
        }
        let identity = identity(for: configuration)
        let values: [String: Any] = [
            kSecValueData as String: Data(token.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        let status = SecItemUpdate(identity as CFDictionary, values as CFDictionary)
        if status == errSecItemNotFound {
            let item = identity.merging(values) { _, new in new }
            let addStatus = SecItemAdd(item as CFDictionary, nil)
            guard addStatus == errSecSuccess else { throw NoteLiteError.keychain(addStatus) }
        } else if status != errSecSuccess {
            throw NoteLiteError.keychain(status)
        }
    }

    private static func identity(for configuration: ServerConfiguration) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: configuration.key
        ]
    }
}
