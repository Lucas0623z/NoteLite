// SPDX-License-Identifier: AGPL-3.0-or-later
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
/// One request owns one token. Cancellation only stores an atomic flag; it never enters Java.
@interface EmbeddedOMRCancellation : NSObject
@property(nonatomic, readonly, getter=isCancelled) BOOL cancelled;
- (void)cancel;
@end

@interface EmbeddedJVM : NSObject
+ (nullable NSString *)runWithResourceRoot:(NSString *)resourceRoot
                                   sandbox:(NSString *)sandbox
                                     error:(NSError **)error
    NS_SWIFT_NAME(run(resourceRoot:sandbox:));
+ (nullable NSString *)recognizeWithResourceRoot:(NSString *)resourceRoot
                                         sandbox:(NSString *)sandbox
                                           input:(NSString *)input
                                           error:(NSError **)error
    NS_SWIFT_NAME(recognize(resourceRoot:sandbox:input:));
+ (nullable NSString *)recognizeWithResourceRoot:(NSString *)resourceRoot
                                         sandbox:(NSString *)sandbox
                                           input:(NSString *)input
                                    cancellation:(EmbeddedOMRCancellation *)cancellation
                                           error:(NSError **)error
    NS_SWIFT_NAME(recognize(resourceRoot:sandbox:input:cancellation:));
/// Legacy current-job convenience. New callers should cancel their own request token.
+ (void)cancelCurrentRecognition;
@end
NS_ASSUME_NONNULL_END
