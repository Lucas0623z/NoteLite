import Foundation

/// A request keeps the account/session that initiated it, including while the
/// system file picker or an asynchronous file read is open.
struct FigmaCloudRequestIdentity {
    let origin: String
    let credential: CloudAccountCredential

    init(origin: String, credential: CloudAccountCredential?, expectedUserID: Any?) throws {
        guard let credential else {
            throw CloudOMRError(code: "account_required", message: "请先登录账户，再导入或读取云端曲谱。", status: 401)
        }
        try credential.validate()
        guard let expectedUserID = expectedUserID as? String,
              UUID(uuidString: expectedUserID) != nil,
              expectedUserID.lowercased() == credential.userID.lowercased() else {
            throw Self.changedAccount()
        }
        self.origin = origin
        self.credential = credential
    }

    var ownerScope: String { origin + "|" + credential.userID }

    func validate(origin: String, credential: CloudAccountCredential?) throws {
        guard let credential, self.origin == origin, self.credential == credential else {
            throw Self.changedAccount()
        }
    }

    private static func changedAccount() -> CloudOMRError {
        CloudOMRError(code: "identity_changed", message: "账户已更改，请重新选择或读取曲谱。", status: 409)
    }
}

/// Practice can be explicitly guest-owned, while account practice and account
/// exports must keep both the user and session that initiated the action.
struct FigmaPracticeRequestIdentity {
    let origin: String
    let credential: CloudAccountCredential?

    init(origin: String, credential: CloudAccountCredential?, expectedUserID: Any?, expectedSessionID: Any?) throws {
        if expectedUserID as? String == "guest" {
            guard credential == nil, expectedSessionID == nil || expectedSessionID is NSNull else { throw Self.changedAccount() }
        } else {
            guard let credential, let user = expectedUserID as? String, UUID(uuidString: user) != nil,
                  user.lowercased() == credential.userID.lowercased(),
                  let session = expectedSessionID as? String, UUID(uuidString: session) != nil,
                  session.lowercased() == credential.sessionID.lowercased() else { throw Self.changedAccount() }
            try credential.validate()
        }
        self.origin = origin
        self.credential = credential
    }

    var ownerScope: String { origin + "|" + (credential?.userID ?? "guest") }

    func validate(origin: String, credential: CloudAccountCredential?) throws {
        guard self.origin == origin, self.credential == credential else { throw Self.changedAccount() }
    }

    private static func changedAccount() -> CloudOMRError {
        CloudOMRError(code: "identity_changed", message: "账户或登录会话已更改，请重新开始当前操作。", status: 409)
    }
}
