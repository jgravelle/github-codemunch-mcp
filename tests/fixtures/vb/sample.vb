Namespace SampleApp

''' <summary>User service.</summary>
Public Class UserService
    Public Const MAX_RETRIES As Integer = 3

    Public Property Name As String

    Public Sub New()
    End Sub

    Public Function GetUser(userId As Integer) As String
        Return userId.ToString()
    End Function
End Class

Public Interface IAuthenticator
    Function Authenticate(token As String) As Boolean
End Interface

Public Delegate Function TokenValidator(token As String) As Boolean

End Namespace
