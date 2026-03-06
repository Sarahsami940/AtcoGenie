using Microsoft.EntityFrameworkCore;

namespace AtcoGenie.Server.Data;

public class ImdDbContext : DbContext
{
    public ImdDbContext(DbContextOptions<ImdDbContext> options) : base(options) { }

    public DbSet<UserMapping> UserMappings { get; set; }
    public DbSet<UserFormRight> UserFormRights { get; set; }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<UserMapping>(entity =>
        {
            entity.ToTable("imd_usermapping");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.AdObjectGuid).HasColumnName("adobjectguid");
            entity.Property(e => e.HcmsEmployeeId).HasColumnName("hcmsemployeeid");
            entity.Property(e => e.Email).HasColumnName("email");
            entity.Property(e => e.DisplayName).HasColumnName("displayname");
            entity.Property(e => e.SamAccountName).HasColumnName("samaccountname");
            entity.Property(e => e.LastSyncedAt).HasColumnName("lastsyncedat");
            entity.Property(e => e.IsActive).HasColumnName("isactive");
            entity.HasIndex(e => e.Email).IsUnique();
            entity.HasIndex(e => e.AdObjectGuid).IsUnique();
        });

        modelBuilder.Entity<UserFormRight>(entity =>
        {
            entity.ToTable("imd_userformrights");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.AdObjectGuid).HasColumnName("adobjectguid");
            entity.Property(e => e.HcmsEmployeeId).HasColumnName("hcmsemployeeid");
            entity.Property(e => e.Email).HasColumnName("email");
            entity.Property(e => e.DisplayName).HasColumnName("displayname");
            entity.Property(e => e.SamAccountName).HasColumnName("samaccountname");
            entity.Property(e => e.IsActive).HasColumnName("isactive");
            entity.Property(e => e.SecurityUserId).HasColumnName("securityuserid");
            entity.Property(e => e.CCode).HasColumnName("ccode");
            entity.Property(e => e.ApplicationCode).HasColumnName("applicationcode");
            entity.Property(e => e.FormId).HasColumnName("formid");
            entity.Property(e => e.AddMode).HasColumnName("addmode");
            entity.Property(e => e.EditMode).HasColumnName("editmode");
            entity.Property(e => e.ViewMode).HasColumnName("viewmode");
            entity.Property(e => e.DeleteMode).HasColumnName("deletemode");
            entity.Property(e => e.LastSyncedAt).HasColumnName("lastsyncedat");
            entity.HasIndex(e => e.HcmsEmployeeId);
            entity.HasIndex(e => e.Email);
            entity.HasIndex(e => e.ApplicationCode);
        });
    }
}

// ─── Authentication table (unchanged) ───
public class UserMapping
{
    public int Id { get; set; }
    public Guid AdObjectGuid { get; set; }
    public required string HcmsEmployeeId { get; set; }
    public required string Email { get; set; }
    public string? DisplayName { get; set; }
    public string? SamAccountName { get; set; }
    public DateTime LastSyncedAt { get; set; }
    public bool IsActive { get; set; }
}

// ─── Full mirror: AD + HCMS + Security form rights ───
public class UserFormRight
{
    public int Id { get; set; }
    public Guid AdObjectGuid { get; set; }
    public required string HcmsEmployeeId { get; set; }
    public required string Email { get; set; }
    public string? DisplayName { get; set; }
    public string? SamAccountName { get; set; }
    public bool IsActive { get; set; }
    public int? SecurityUserId { get; set; }
    public string? CCode { get; set; }
    public string? ApplicationCode { get; set; }
    public string? FormId { get; set; }
    public bool? AddMode { get; set; }
    public bool? EditMode { get; set; }
    public bool? ViewMode { get; set; }
    public bool? DeleteMode { get; set; }
    public DateTime LastSyncedAt { get; set; }
}
