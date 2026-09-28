// SPDX-License-Identifier: AGPL-3.0-or-later
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
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
+ (void)cancelCurrentRecognition;
@end
NS_ASSUME_NONNULL_END
